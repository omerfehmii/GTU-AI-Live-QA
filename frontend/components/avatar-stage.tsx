"use client";

import { Suspense, useEffect, useMemo, useRef } from "react";

import { Html, useAnimations } from "@react-three/drei";
import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber";
import {
  Box3,
  ACESFilmicToneMapping,
  DoubleSide,
  Euler,
  Group,
  MathUtils,
  Mesh,
  Object3D,
  SRGBColorSpace,
  Texture,
  TextureLoader,
  Vector3,
} from "three";
import { FBXLoader } from "three/examples/jsm/loaders/FBXLoader.js";
import { clone } from "three/examples/jsm/utils/SkeletonUtils.js";

import type { AvatarState } from "@/lib/types";

const MODEL_PATH = "/avatars/stylized-cartoon-girl-rigged-character/source/MJ.fbx";
const MODEL_TEXTURE_PATH = "/avatars/stylized-cartoon-girl-rigged-character/textures/";
const HAIR_TEXTURE_PATH = `${MODEL_TEXTURE_PATH}model.png`;
const AVATAR_VIEWS = {
  default: {
    cameraDistance: 2.85,
    cameraFocusY: 1.18,
    fov: 24,
    modelLift: 0.08,
    scaleMultiplier: 1,
    targetEyeLine: 1.3,
  },
  classroom: {
    cameraDistance: 2.38,
    cameraFocusY: 1.23,
    fov: 23,
    modelLift: -0.3,
    scaleMultiplier: 1.24,
    targetEyeLine: 1.32,
  },
  studio: {
    cameraDistance: 2.34,
    cameraFocusY: 1.23,
    fov: 23,
    modelLift: -0.035,
    scaleMultiplier: 1.24,
    targetEyeLine: 1.365,
  },
} as const;

type PreparedAvatar = {
  scene: Object3D;
  scale: number;
  eyeHeight: number;
};

type MorphMesh = Mesh & {
  morphTargetDictionary?: Record<string, number>;
  morphTargetInfluences?: number[];
};

type AudioPlaybackSnapshot = {
  currentTime: number;
  duration: number;
  isPlaying: boolean;
};

type VisemeId = "rest" | "open" | "wide" | "round" | "closed" | "plosive" | "dental";

type VisemeCue = {
  at: number;
  emphasis: number;
  viseme: VisemeId;
};

type VisemeTargets = {
  close: number;
  dental: number;
  lipPart: number;
  open: number;
  plosive: number;
  round: number;
  wide: number;
};

const morphTargetNameCache = new WeakMap<MorphMesh, Map<string, string | null>>();

function normalizeMorphName(name: string) {
  return name.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function resolveMorphTargetName(mesh: MorphMesh, names: string[]) {
  const dictionary = mesh.morphTargetDictionary;
  if (!dictionary) {
    return null;
  }

  const cacheKey = names.join("|");
  let meshCache = morphTargetNameCache.get(mesh);
  if (!meshCache) {
    meshCache = new Map();
    morphTargetNameCache.set(mesh, meshCache);
  }

  if (meshCache.has(cacheKey)) {
    return meshCache.get(cacheKey) ?? null;
  }

  const dictionaryNames = Object.keys(dictionary);
  const normalizedNames = names.map(normalizeMorphName);
  const exactMatch = names.find((name) => dictionary[name] !== undefined);
  const normalizedMatch =
    exactMatch ??
    dictionaryNames.find((dictionaryName) => {
      const normalizedDictionaryName = normalizeMorphName(dictionaryName);
      return normalizedNames.some(
        (normalizedName) =>
          normalizedDictionaryName === normalizedName ||
          normalizedDictionaryName.endsWith(normalizedName),
      );
    }) ??
    dictionaryNames.find((dictionaryName) => {
      const normalizedDictionaryName = normalizeMorphName(dictionaryName);
      return normalizedNames.some((normalizedName) => normalizedDictionaryName.includes(normalizedName));
    }) ??
    null;

  meshCache.set(cacheKey, normalizedMatch);
  return normalizedMatch;
}

function AvatarFallback() {
  return (
    <div className="avatar-fallback">
      <p>3D avatar yukleniyor...</p>
    </div>
  );
}

function dampInfluence(
  mesh: MorphMesh,
  names: string | string[],
  target: number,
  easing = 0.18,
) {
  const dictionary = mesh.morphTargetDictionary;
  const influences = mesh.morphTargetInfluences;
  const resolvedName = resolveMorphTargetName(mesh, Array.isArray(names) ? names : [names]);
  if (!resolvedName) {
    return;
  }

  const index = dictionary?.[resolvedName];

  if (index === undefined || !influences) {
    return;
  }

  influences[index] = MathUtils.lerp(influences[index] ?? 0, MathUtils.clamp(target, 0, 1), easing);
}

function findObjectByPartialName(scene: Object3D, patterns: string[]): Object3D | undefined {
  const loweredPatterns = patterns.map((pattern) => pattern.toLowerCase());

  let match: Object3D | undefined;
  scene.traverse((child) => {
    if (match || !child.name) {
      return;
    }

    const loweredName = child.name.toLowerCase();
    if (loweredPatterns.some((pattern) => loweredName.includes(pattern))) {
      match = child;
    }
  });

  return match;
}

function applyRelaxedArmPose(scene: Object3D) {
  const leftArm = findObjectByPartialName(scene, ["leftarm_", "leftupperarm", "l_upperarm"]);
  const rightArm = findObjectByPartialName(scene, ["rightarm_", "rightupperarm", "r_upperarm"]);
  const leftForeArm = findObjectByPartialName(scene, ["leftforearm_", "leftforearm", "l_forearm"]);
  const rightForeArm = findObjectByPartialName(scene, ["rightforearm_", "rightforearm", "r_forearm"]);

  if (leftArm) {
    leftArm.rotation.z -= 1.1;
  }
  if (rightArm) {
    rightArm.rotation.z += 1.1;
  }
  if (leftForeArm) {
    leftForeArm.rotation.z -= 0.25;
  }
  if (rightForeArm) {
    rightForeArm.rotation.z += 0.25;
  }
}

function configureAvatarMaterials(scene: Object3D, hairTexture: Texture) {
  hairTexture.colorSpace = SRGBColorSpace;
  hairTexture.needsUpdate = true;

  scene.traverse((child) => {
    if (!("isMesh" in child) || !(child as Mesh).isMesh) {
      return;
    }

    const mesh = child as Mesh;
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];

    for (const material of materials) {
      if (!material) {
        continue;
      }

      const materialName = material.name.toLowerCase();
      const meshName = mesh.name.toLowerCase();
      const isHairMaterial = meshName.includes("modelmesh") || materialName.includes("lambert10");
      const isCutoutMaterial =
        isHairMaterial ||
        materialName.includes("eyelash") ||
        materialName.includes("tearline") ||
        materialName.includes("occlusion");

      if (isHairMaterial && "map" in material) {
        material.map = hairTexture;
        material.opacity = 1;
        material.depthWrite = true;
        material.transparent = false;
        material.alphaTest = 0.14;
        material.side = DoubleSide;
        if ("alphaMap" in material) {
          material.alphaMap = null;
        }
        const colorMaterial = material as typeof material & { color?: { set: (color: string) => void } };
        colorMaterial.color?.set("#ffffff");
        mesh.renderOrder = 2;
        material.needsUpdate = true;
        continue;
      }

      if (isCutoutMaterial) {
        material.opacity = 1;
        material.depthWrite = false;
        material.transparent = true;
        material.alphaTest = Math.max(material.alphaTest ?? 0, 0.04);
        material.side = DoubleSide;
        material.needsUpdate = true;
      }
    }
  });
}

function getMeshBounds(scene: Object3D) {
  const bounds = new Box3();
  const childBounds = new Box3();
  let hasMesh = false;

  scene.traverse((child) => {
    if (!("isMesh" in child) || !(child as Mesh).isMesh) {
      return;
    }

    childBounds.setFromObject(child);
    if (childBounds.isEmpty()) {
      return;
    }

    if (!hasMesh) {
      bounds.copy(childBounds);
      hasMesh = true;
      return;
    }

    bounds.union(childBounds);
  });

  return hasMesh ? bounds : new Box3().setFromObject(scene);
}

function AvatarModel({
  audioDurationMs,
  avatarState,
  speakingUntil,
  speechKey,
  speechText,
  useLocalSpeech,
  view,
  audioLevelRef,
  audioPlaybackRef,
}: {
  audioDurationMs?: number | null;
  avatarState: AvatarState;
  speakingUntil: React.RefObject<number>;
  speechKey: string | null;
  speechText: string;
  useLocalSpeech: boolean;
  view: (typeof AVATAR_VIEWS)[keyof typeof AVATAR_VIEWS];
  audioLevelRef?: React.RefObject<number>;
  audioPlaybackRef?: React.RefObject<AudioPlaybackSnapshot>;
}) {
  const root = useRef<Group>(null);
  const speakingStartedAt = useRef(0);
  const sourceModel = useLoader(FBXLoader, MODEL_PATH, (loader) => {
    loader.setResourcePath(MODEL_TEXTURE_PATH);
  });
  const hairTexture = useLoader(TextureLoader, HAIR_TEXTURE_PATH);
  const { animations } = sourceModel;
  const prepared = useMemo<PreparedAvatar>(() => {
    const clonedScene = clone(sourceModel);
    clonedScene.traverse((child) => {
      if ("isMesh" in child && (child as Mesh).isMesh) {
        child.frustumCulled = false;
      }
    });
    configureAvatarMaterials(clonedScene, hairTexture);
    applyRelaxedArmPose(clonedScene);
    clonedScene.updateMatrixWorld(true);

    const bounds = getMeshBounds(clonedScene);
    const size = bounds.getSize(new Vector3());
    const center = bounds.getCenter(new Vector3());
    const leftEye =
      findObjectByPartialName(clonedScene, ["lefteye", "left_eye"]) ??
      findObjectByPartialName(clonedScene, ["eye_l"]);
    const rightEye =
      findObjectByPartialName(clonedScene, ["righteye", "right_eye"]) ??
      findObjectByPartialName(clonedScene, ["eye_r"]);
    const head =
      findObjectByPartialName(clonedScene, [":head", " head", "head"]) ??
      findObjectByPartialName(clonedScene, ["neck"]);
    const leftEyeWorld = leftEye?.getWorldPosition(new Vector3());
    const rightEyeWorld = rightEye?.getWorldPosition(new Vector3());
    const focusPoint =
      leftEyeWorld && rightEyeWorld
        ? leftEyeWorld.clone().add(rightEyeWorld).multiplyScalar(0.5)
        : head?.getWorldPosition(new Vector3()) ?? new Vector3(center.x, bounds.max.y * 0.82, center.z);

    const width = Math.max(size.x, size.z, 1);
    const height = Math.max(size.y, 1);
    const baseScale = Math.min(2.15 / height, 1.7 / width);
    const portraitScale = baseScale * view.scaleMultiplier;
    const eyeHeight = Math.max(focusPoint.y - bounds.min.y, height * 0.78);

    clonedScene.position.x = -focusPoint.x * portraitScale;
    clonedScene.position.y = -bounds.min.y * portraitScale;
    clonedScene.position.z = -focusPoint.z * portraitScale;

    return { scene: clonedScene, scale: portraitScale, eyeHeight };
  }, [hairTexture, sourceModel]);
  const { actions } = useAnimations(animations, root);
  const blinkSeed = useRef(Math.random() * Math.PI * 2);
  const morphMeshes = useMemo(() => {
    const meshes: MorphMesh[] = [];

    prepared.scene.traverse((child) => {
      if ("morphTargetDictionary" in child && "morphTargetInfluences" in child) {
        meshes.push(child as MorphMesh);
      }
    });

    return meshes;
  }, [prepared.scene]);
  const jawBone = useMemo(
    () => findObjectByPartialName(prepared.scene, ["jawroot", "lowerjaw", "jaw"]),
    [prepared.scene],
  );
  const jawRestRotation = useMemo(() => jawBone?.rotation.clone() ?? new Euler(), [jawBone]);
  const headBone = useMemo(
    () => findObjectByPartialName(prepared.scene, ["cc_base_head", "head_038", "head"]),
    [prepared.scene],
  );
  const neckBone = useMemo(
    () => findObjectByPartialName(prepared.scene, ["cc_base_necktwist02", "necktwist02", "neck"]),
    [prepared.scene],
  );
  const headRestRotation = useMemo(() => headBone?.rotation.clone() ?? new Euler(), [headBone]);
  const neckRestRotation = useMemo(() => neckBone?.rotation.clone() ?? new Euler(), [neckBone]);
  const visemeTimeline = useMemo(() => buildVisemeTimeline(speechText), [speechText]);
  const estimatedDurationMs = useMemo(
    () => estimateSpeechDurationMs(speechText, audioDurationMs),
    [audioDurationMs, speechText],
  );

  useEffect(() => {
    if (avatarState === "speaking") {
      speakingStartedAt.current = performance.now();
    }
  }, [avatarState, speechKey]);

  useEffect(() => {
    const preferredAction =
      actions?.idle ??
      actions?.Idle ??
      actions?.happy ??
      actions?.Happy;

    if (!preferredAction) {
      return;
    }

    preferredAction?.reset().fadeIn(0.35).play();

    return () => {
      preferredAction?.fadeOut(0.2);
    };
  }, [actions]);

  useFrame((state) => {
    if (!root.current) {
      return;
    }

    const elapsed = state.clock.elapsedTime;
    const speaking = (useLocalSpeech && performance.now() < speakingUntil.current) || avatarState === "speaking";
    const thinking = avatarState === "thinking";
    const error = avatarState === "error";
    const audioLevel = MathUtils.clamp(audioLevelRef?.current ?? 0, 0, 1);
    const fallbackLevel = speaking ? 0.16 + visemeCycleFromTime(elapsed, 8.7, 0) * 0.42 : 0;
    const speechLevel = speaking ? MathUtils.clamp(Math.max(audioLevel, audioLevel > 0.03 ? fallbackLevel * 0.3 : fallbackLevel), 0, 1) : 0;
    const speechProgress = getSpeechProgress({
      audioPlayback: audioPlaybackRef?.current,
      elapsedMs: performance.now() - speakingStartedAt.current,
      fallbackDurationMs: estimatedDurationMs,
      speaking,
    });
    const visemeTargets = getVisemeTargets(visemeTimeline, speechProgress, speechLevel);
    const idleYaw = Math.sin(elapsed * 0.55) * (thinking ? 0.04 : 0.08);
    const idlePitch = Math.sin(elapsed * 0.35) * (thinking ? 0.06 : 0.03);
    const thinkingBob = thinking ? Math.sin(elapsed * 3.4) * 0.018 : 0;
    const baseY = view.targetEyeLine - (prepared.eyeHeight * prepared.scale);

    root.current.rotation.y = MathUtils.lerp(
      root.current.rotation.y,
      error ? -0.04 : idleYaw,
      0.06,
    );
    root.current.rotation.x = MathUtils.lerp(root.current.rotation.x, idlePitch + thinkingBob, 0.08);
    root.current.position.y = MathUtils.lerp(
      root.current.position.y,
      baseY + view.modelLift,
      0.08,
    );
    root.current.position.z = MathUtils.lerp(root.current.position.z, 0, 0.08);

    const speechGesture = speaking ? MathUtils.clamp(0.25 + speechLevel * 0.75, 0, 1) : 0;
    if (headBone) {
      headBone.rotation.x = MathUtils.lerp(
        headBone.rotation.x,
        headRestRotation.x + Math.sin(elapsed * 2.3) * 0.012 * speechGesture - 0.006 * speechGesture,
        0.08,
      );
      headBone.rotation.y = MathUtils.lerp(
        headBone.rotation.y,
        headRestRotation.y + Math.sin(elapsed * 1.7 + 0.8) * 0.018 * speechGesture,
        0.08,
      );
      headBone.rotation.z = MathUtils.lerp(
        headBone.rotation.z,
        headRestRotation.z + Math.sin(elapsed * 2.0 + 1.7) * 0.01 * speechGesture,
        0.08,
      );
    }
    if (neckBone) {
      neckBone.rotation.x = MathUtils.lerp(
        neckBone.rotation.x,
        neckRestRotation.x + Math.sin(elapsed * 1.5 + 1.1) * 0.006 * speechGesture,
        0.06,
      );
      neckBone.rotation.y = MathUtils.lerp(
        neckBone.rotation.y,
        neckRestRotation.y + Math.sin(elapsed * 1.2 + 0.4) * 0.008 * speechGesture,
        0.06,
      );
    }

    const blink = Math.max(0, Math.sin(elapsed * 0.8 + blinkSeed.current) - 0.94) * 14;
    const mouthOpenTarget = speaking ? visemeTargets.open : 0.015;
    const lipPartTarget = speaking ? visemeTargets.lipPart : 0;
    const roundTarget = speaking ? visemeTargets.round : 0;
    const wideTarget = speaking ? visemeTargets.wide : 0;
    const closeTarget = speaking ? visemeTargets.close : 0.08;

    for (const mesh of morphMeshes) {
      dampInfluence(mesh, ["eyeBlinkLeft", "Eye_Blink_L"], blink);
      dampInfluence(mesh, ["eyeBlinkRight", "Eye_Blink_R"], blink);
      dampInfluence(mesh, ["eyesClosed", "Eye_Blink"], blink * 0.65);
      dampInfluence(mesh, ["mouthSmile", "Mouth_Smile"], speaking ? 0.05 + speechLevel * 0.05 : error ? 0 : 0.06, 0.12);
      dampInfluence(mesh, ["mouthSmileLeft", "Mouth_Smile_L"], speaking ? 0.04 + speechLevel * 0.04 : 0.035, 0.12);
      dampInfluence(mesh, ["mouthSmileRight", "Mouth_Smile_R"], speaking ? 0.04 + speechLevel * 0.04 : 0.035, 0.12);
      dampInfluence(
        mesh,
        ["jawOpen", "Mouth_Lips_Jaw_Adjust", "Mouth_Open", "Lip_Open"],
        mouthOpenTarget,
        0.22,
      );
      dampInfluence(
        mesh,
        ["mouthOpen", "Mouth_Lips_Open", "Mouth_Open", "Open"],
        mouthOpenTarget * 0.85,
        0.24,
      );
      dampInfluence(mesh, ["mouthClose", "Mouth_Lips_Tight", "Tight"], closeTarget, 0.18);
      dampInfluence(mesh, ["viseme_aa", "Mouth_Lips_Part", "Open", "Wide"], lipPartTarget, 0.26);
      dampInfluence(mesh, ["viseme_O", "Tight_O", "Mouth_Pucker_Open", "Mouth_Pucker"], roundTarget, 0.2);
      dampInfluence(mesh, ["viseme_I", "Mouth_Widen", "Mouth_Widen_Sides", "Wide"], wideTarget, 0.18);
      dampInfluence(mesh, ["viseme_PP", "Explosive", "Mouth_Plosive"], visemeTargets.plosive, 0.3);
      dampInfluence(mesh, ["viseme_FF", "Dental_Lip", "Affricate"], visemeTargets.dental, 0.22);
      dampInfluence(mesh, ["viseme_sil", "Mouth_Lips_Tuck"], speaking ? 0.01 : 0.04, 0.16);
    }

    if (jawBone && morphMeshes.length === 0) {
      const jawOpen = speaking ? speechLevel * 0.18 : 0;
      jawBone.rotation.x = MathUtils.lerp(jawBone.rotation.x, jawRestRotation.x + jawOpen, 0.22);
    }
  });

  return (
    <group ref={root}>
      <primitive object={prepared.scene} scale={prepared.scale} />
    </group>
  );
}

function HeadshotCamera({
  distance,
  focusY,
}: {
  distance: number;
  focusY: number;
}) {
  const { camera } = useThree();

  useEffect(() => {
    camera.position.set(0, focusY, distance);
    camera.lookAt(0, focusY, 0);
    camera.updateProjectionMatrix();
  }, [camera, distance, focusY]);

  return null;
}

export function AvatarStage({
  audioDurationMs,
  speechKey,
  speechText = "",
  state,
  theme = "default",
  audioLevelRef,
  audioPlaybackRef,
}: {
  audioDurationMs?: number | null;
  speechKey: string | null;
  speechText?: string;
  state?: AvatarState;
  theme?: "default" | "classroom" | "studio";
  audioLevelRef?: React.RefObject<number>;
  audioPlaybackRef?: React.RefObject<AudioPlaybackSnapshot>;
}) {
  const speakingUntil = useRef(0);
  const view = AVATAR_VIEWS[theme];
  const focusY = view.cameraFocusY;
  const avatarState = state ?? "idle";
  const useLocalSpeech = state === undefined;
  const isStudioTheme = theme === "studio";
  const canvasBackdrop = isStudioTheme ? "#f8fafc" : "#08131b";

  useEffect(() => {
    if (!speechKey) {
      return;
    }
    if (!useLocalSpeech && state !== "speaking") {
      speakingUntil.current = 0;
      return;
    }

    const speechDurationMs = Math.min(Math.max(speechText.length * 45, 3200), 15000);
    speakingUntil.current = performance.now() + speechDurationMs;
  }, [speechKey, speechText, state, useLocalSpeech]);

  return (
    <div className={`avatar-stage avatar-stage-portrait avatar-stage-${theme}`}>
      <Canvas
        camera={{ position: [0, focusY, view.cameraDistance], fov: view.fov, near: 0.01, far: 20 }}
        dpr={[1, 1.5]}
        fallback={<AvatarFallback />}
        gl={{ alpha: true }}
        onCreated={({ gl }) => {
          gl.toneMapping = ACESFilmicToneMapping;
          gl.toneMappingExposure = isStudioTheme ? 1.04 : 1;
        }}
      >
        <HeadshotCamera distance={view.cameraDistance} focusY={focusY} />
        {isStudioTheme ? null : <color attach="background" args={[canvasBackdrop]} />}
        <fog attach="fog" args={[canvasBackdrop, 2.8, 6.2]} />
        {isStudioTheme ? (
          <>
            <ambientLight intensity={1.08} />
            <hemisphereLight args={["#fff7eb", "#dbe7ff", 0.74]} />
            <directionalLight
              color="#fff0d6"
              intensity={1.22}
              position={[-2.7, 3.2, 3.6]}
            />
            <directionalLight color="#dbe8ff" intensity={0.48} position={[2.8, 1.3, 2.3]} />
            <pointLight color="#fff1db" distance={4.2} intensity={0.45} position={[0, -0.45, 2.4]} />
          </>
        ) : (
          <>
            <ambientLight intensity={1.65} />
            <directionalLight position={[2.5, 1.8, 3.2]} intensity={2.2} />
            <directionalLight position={[-2.2, 0.5, 2.4]} intensity={1.1} color="#67d9ff" />
            <spotLight position={[0, 2.8, 3.4]} angle={0.42} penumbra={0.7} intensity={28} />
          </>
        )}
        <Suspense
          fallback={
            <Html center>
              <div className="avatar-loader">Model hazirlaniyor...</div>
            </Html>
          }
        >
          <AvatarModel
            audioDurationMs={audioDurationMs}
            avatarState={avatarState}
            audioLevelRef={audioLevelRef}
            audioPlaybackRef={audioPlaybackRef}
            speechKey={speechKey}
            speechText={speechText}
            speakingUntil={speakingUntil}
            useLocalSpeech={useLocalSpeech}
            view={view}
          />
        </Suspense>
      </Canvas>
    </div>
  );
}

function visemeCycleFromTime(elapsed: number, speed: number, phase: number) {
  return (Math.sin(elapsed * speed + phase) + 1) * 0.5;
}

function estimateSpeechDurationMs(text: string, audioDurationMs?: number | null) {
  if (audioDurationMs && audioDurationMs > 0) {
    return audioDurationMs;
  }

  return Math.min(Math.max(text.length * 48, 3200), 22000);
}

function classifyViseme(character: string): { emphasis: number; viseme: VisemeId; weight: number } {
  const char = character.toLocaleLowerCase("tr-TR");

  if ("aı".includes(char)) {
    return { emphasis: 0.95, viseme: "open", weight: 1.25 };
  }
  if ("ei".includes(char)) {
    return { emphasis: 0.8, viseme: "wide", weight: 1.1 };
  }
  if ("oöuü".includes(char)) {
    return { emphasis: 0.9, viseme: "round", weight: 1.25 };
  }
  if ("pbm".includes(char)) {
    return { emphasis: 1, viseme: "plosive", weight: 0.75 };
  }
  if ("fv".includes(char)) {
    return { emphasis: 0.85, viseme: "dental", weight: 0.85 };
  }
  if ("tdkgcqçszşjrlrynnhğ".includes(char)) {
    return { emphasis: 0.42, viseme: "closed", weight: 0.65 };
  }
  if (/[.!?;:]/.test(char)) {
    return { emphasis: 0.25, viseme: "rest", weight: 3 };
  }
  if (/[,\s]/.test(char)) {
    return { emphasis: 0.18, viseme: "rest", weight: 1.45 };
  }

  return { emphasis: 0.18, viseme: "rest", weight: 0.5 };
}

function buildVisemeTimeline(text: string): VisemeCue[] {
  const cues: Array<VisemeCue & { weight: number }> = [];
  let previous: (VisemeCue & { weight: number }) | undefined;

  for (const character of text) {
    const classified = classifyViseme(character);
    if (previous && previous.viseme === classified.viseme) {
      previous.weight += classified.weight;
      previous.emphasis = Math.max(previous.emphasis, classified.emphasis);
      continue;
    }

    previous = {
      at: 0,
      emphasis: classified.emphasis,
      viseme: classified.viseme,
      weight: classified.weight,
    };
    cues.push(previous);
  }

  if (cues.length === 0) {
    return [
      { at: 0, emphasis: 0, viseme: "rest" },
      { at: 1, emphasis: 0, viseme: "rest" },
    ];
  }

  const totalWeight = cues.reduce((total, cue) => total + cue.weight, 0);
  let cursor = 0;
  const timeline: VisemeCue[] = [{ at: 0, emphasis: 0, viseme: "rest" }];

  for (const cue of cues) {
    cursor += cue.weight;
    timeline.push({
      at: MathUtils.clamp(cursor / totalWeight, 0, 1),
      emphasis: cue.emphasis,
      viseme: cue.viseme,
    });
  }

  timeline.push({ at: 1, emphasis: 0, viseme: "rest" });
  return timeline;
}

function getSpeechProgress({
  audioPlayback,
  elapsedMs,
  fallbackDurationMs,
  speaking,
}: {
  audioPlayback?: AudioPlaybackSnapshot;
  elapsedMs: number;
  fallbackDurationMs: number;
  speaking: boolean;
}) {
  if (!speaking) {
    return 0;
  }

  if (audioPlayback?.isPlaying && audioPlayback.duration > 0) {
    return MathUtils.clamp(audioPlayback.currentTime / audioPlayback.duration, 0, 1);
  }

  return MathUtils.clamp(elapsedMs / fallbackDurationMs, 0, 1);
}

function getBaseVisemeTargets(viseme: VisemeId): VisemeTargets {
  switch (viseme) {
    case "open":
      return { close: 0.02, dental: 0, lipPart: 0.62, open: 0.52, plosive: 0, round: 0.04, wide: 0.08 };
    case "wide":
      return { close: 0.04, dental: 0, lipPart: 0.34, open: 0.26, plosive: 0, round: 0, wide: 0.36 };
    case "round":
      return { close: 0.02, dental: 0, lipPart: 0.3, open: 0.31, plosive: 0, round: 0.52, wide: 0 };
    case "closed":
      return { close: 0.2, dental: 0, lipPart: 0.04, open: 0.05, plosive: 0, round: 0, wide: 0.04 };
    case "plosive":
      return { close: 0.5, dental: 0, lipPart: 0, open: 0.02, plosive: 0.46, round: 0.02, wide: 0 };
    case "dental":
      return { close: 0.16, dental: 0.42, lipPart: 0.08, open: 0.08, plosive: 0, round: 0, wide: 0.18 };
    case "rest":
    default:
      return { close: 0.08, dental: 0, lipPart: 0, open: 0.015, plosive: 0, round: 0, wide: 0 };
  }
}

function blendVisemeTargets(from: VisemeTargets, to: VisemeTargets, amount: number): VisemeTargets {
  return {
    close: MathUtils.lerp(from.close, to.close, amount),
    dental: MathUtils.lerp(from.dental, to.dental, amount),
    lipPart: MathUtils.lerp(from.lipPart, to.lipPart, amount),
    open: MathUtils.lerp(from.open, to.open, amount),
    plosive: MathUtils.lerp(from.plosive, to.plosive, amount),
    round: MathUtils.lerp(from.round, to.round, amount),
    wide: MathUtils.lerp(from.wide, to.wide, amount),
  };
}

function scaleVisemeTargets(targets: VisemeTargets, emphasis: number, speechLevel: number): VisemeTargets {
  const intensity = MathUtils.clamp(0.42 + emphasis * 0.55 + speechLevel * 0.48, 0, 1.22);

  return {
    close: MathUtils.clamp(targets.close * (0.7 + emphasis * 0.45), 0, 1),
    dental: MathUtils.clamp(targets.dental * intensity, 0, 1),
    lipPart: MathUtils.clamp(targets.lipPart * intensity, 0, 1),
    open: MathUtils.clamp(targets.open * intensity + speechLevel * 0.08, 0, 1),
    plosive: MathUtils.clamp(targets.plosive * (0.8 + emphasis * 0.45), 0, 1),
    round: MathUtils.clamp(targets.round * intensity, 0, 1),
    wide: MathUtils.clamp(targets.wide * intensity, 0, 1),
  };
}

function smoothstep(edge0: number, edge1: number, value: number) {
  const t = MathUtils.clamp((value - edge0) / (edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
}

function getVisemeTargets(timeline: VisemeCue[], progress: number, speechLevel: number): VisemeTargets {
  let activeIndex = 0;
  for (let index = 0; index < timeline.length; index += 1) {
    if (timeline[index].at <= progress) {
      activeIndex = index;
      continue;
    }
    break;
  }

  const activeCue = timeline[activeIndex] ?? timeline[0];
  const nextCue = timeline[Math.min(activeIndex + 1, timeline.length - 1)] ?? activeCue;
  const span = Math.max(nextCue.at - activeCue.at, 0.001);
  const localProgress = MathUtils.clamp((progress - activeCue.at) / span, 0, 1);
  const blend = smoothstep(0.64, 1, localProgress);
  const emphasis = MathUtils.lerp(activeCue.emphasis, nextCue.emphasis, blend);
  const targets = blendVisemeTargets(
    getBaseVisemeTargets(activeCue.viseme),
    getBaseVisemeTargets(nextCue.viseme),
    blend,
  );

  return scaleVisemeTargets(targets, emphasis, speechLevel);
}

useLoader.preload(FBXLoader, MODEL_PATH, (loader) => {
  loader.setResourcePath(MODEL_TEXTURE_PATH);
});
