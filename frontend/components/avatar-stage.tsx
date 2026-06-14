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
  LinearMipmapLinearFilter,
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
const HAIR_TEXTURE_PATH = `${MODEL_TEXTURE_PATH}model-soft.png`;
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

const SPEECH_MOUTH_GAIN = 1.24;
const SPEECH_PULSE_GAIN = 1.42;
const SPEECH_ARM_GESTURE_GAIN = 0.38;

type GestureRig = {
  leftClavicle?: Object3D;
  leftForeArm?: Object3D;
  leftHand?: Object3D;
  leftUpperArm?: Object3D;
  rightClavicle?: Object3D;
  rightForeArm?: Object3D;
  rightHand?: Object3D;
  rightUpperArm?: Object3D;
};

type GestureRigRest = Record<keyof GestureRig, Euler>;

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

type TunableHairMaterial = {
  alphaHash?: boolean;
  alphaMap?: Texture | null;
  alphaTest?: number;
  clearcoat?: number;
  clearcoatRoughness?: number;
  color?: { set: (color: string) => void };
  depthTest?: boolean;
  depthWrite?: boolean;
  emissive?: { set: (color: string) => void };
  emissiveIntensity?: number;
  forceSinglePass?: boolean;
  map?: Texture | null;
  metalness?: number;
  needsUpdate?: boolean;
  opacity?: number;
  premultipliedAlpha?: boolean;
  reflectivity?: number;
  roughness?: number;
  shininess?: number;
  side?: number;
  specularColor?: { set: (color: string) => void };
  specularIntensity?: number;
  transparent?: boolean;
};

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

function restRotation(bone?: Object3D) {
  return bone?.rotation.clone() ?? new Euler();
}

function dampBoneRotation(
  bone: Object3D | undefined,
  rest: Euler,
  offset: { x?: number; y?: number; z?: number },
  easing = 0.08,
) {
  if (!bone) {
    return;
  }

  bone.rotation.x = MathUtils.lerp(bone.rotation.x, rest.x + (offset.x ?? 0), easing);
  bone.rotation.y = MathUtils.lerp(bone.rotation.y, rest.y + (offset.y ?? 0), easing);
  bone.rotation.z = MathUtils.lerp(bone.rotation.z, rest.z + (offset.z ?? 0), easing);
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

function configureHairTexture(hairTexture: Texture) {
  hairTexture.colorSpace = SRGBColorSpace;
  hairTexture.generateMipmaps = true;
  hairTexture.minFilter = LinearMipmapLinearFilter;
  hairTexture.anisotropy = Math.max(hairTexture.anisotropy, 8);
  hairTexture.needsUpdate = true;
}

function tuneHairMaterial(material: TunableHairMaterial, hairTexture: Texture) {
  material.map = hairTexture;
  material.alphaMap = null;
  material.opacity = 1;
  material.transparent = false;
  material.alphaHash = false;
  material.alphaTest = 0.125;
  material.depthTest = true;
  material.depthWrite = true;
  material.premultipliedAlpha = false;
  material.forceSinglePass = true;
  material.side = DoubleSide;
  material.color?.set("#f7efe6");
  material.emissive?.set("#21150f");
  if ("emissiveIntensity" in material) {
    material.emissiveIntensity = 0.045;
  }
  if ("metalness" in material) {
    material.metalness = 0;
  }
  if ("roughness" in material) {
    material.roughness = 0.72;
  }
  if ("specularIntensity" in material) {
    material.specularIntensity = 0.28;
  }
  material.specularColor?.set("#6b4a36");
  if ("shininess" in material) {
    material.shininess = 18;
  }
  if ("reflectivity" in material) {
    material.reflectivity = 0.16;
  }
  if ("clearcoat" in material) {
    material.clearcoat = 0.08;
  }
  if ("clearcoatRoughness" in material) {
    material.clearcoatRoughness = 0.88;
  }
  material.needsUpdate = true;
}

function configureAvatarMaterials(scene: Object3D, hairTexture: Texture) {
  configureHairTexture(hairTexture);

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
      const isHairMaterial =
        meshName.includes("modelmesh") || meshName.includes("model:mesh") || materialName.includes("lambert10");
      const isCutoutMaterial =
        isHairMaterial ||
        materialName.includes("eyelash") ||
        materialName.includes("tearline") ||
        materialName.includes("occlusion");

      if (isHairMaterial && "map" in material) {
        tuneHairMaterial(material as TunableHairMaterial, hairTexture);
        mesh.renderOrder = 2;
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
  const lipSyncState = useRef({
    lastEnergyAt: 0,
    level: 0,
    meterSeen: false,
  });
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
  const gestureRig = useMemo<GestureRig>(
    () => ({
      leftClavicle: findObjectByPartialName(prepared.scene, ["cc_base_l_clavicle", "l_clavicle"]),
      leftForeArm: findObjectByPartialName(prepared.scene, ["cc_base_l_forearm", "l_forearm"]),
      leftHand: findObjectByPartialName(prepared.scene, ["cc_base_l_hand", "l_hand"]),
      leftUpperArm: findObjectByPartialName(prepared.scene, ["cc_base_l_upperarm", "l_upperarm"]),
      rightClavicle: findObjectByPartialName(prepared.scene, ["cc_base_r_clavicle", "r_clavicle"]),
      rightForeArm: findObjectByPartialName(prepared.scene, ["cc_base_r_forearm", "r_forearm"]),
      rightHand: findObjectByPartialName(prepared.scene, ["cc_base_r_hand", "r_hand"]),
      rightUpperArm: findObjectByPartialName(prepared.scene, ["cc_base_r_upperarm", "r_upperarm"]),
    }),
    [prepared.scene],
  );
  const gestureRigRest = useMemo<GestureRigRest>(
    () => ({
      leftClavicle: restRotation(gestureRig.leftClavicle),
      leftForeArm: restRotation(gestureRig.leftForeArm),
      leftHand: restRotation(gestureRig.leftHand),
      leftUpperArm: restRotation(gestureRig.leftUpperArm),
      rightClavicle: restRotation(gestureRig.rightClavicle),
      rightForeArm: restRotation(gestureRig.rightForeArm),
      rightHand: restRotation(gestureRig.rightHand),
      rightUpperArm: restRotation(gestureRig.rightUpperArm),
    }),
    [gestureRig],
  );
  const visemeTimeline = useMemo(() => buildVisemeTimeline(speechText), [speechText]);
  const estimatedDurationMs = useMemo(
    () => estimateSpeechDurationMs(speechText, audioDurationMs),
    [audioDurationMs, speechText],
  );

  useEffect(() => {
    if (avatarState === "speaking") {
      speakingStartedAt.current = performance.now();
      lipSyncState.current = {
        lastEnergyAt: performance.now(),
        level: 0,
        meterSeen: false,
      };
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
    const now = performance.now();
    const speaking = (useLocalSpeech && performance.now() < speakingUntil.current) || avatarState === "speaking";
    const thinking = avatarState === "thinking";
    const error = avatarState === "error";
    const rawAudioLevel = MathUtils.clamp(audioLevelRef?.current ?? 0, 0, 1);
    const audioPlaying = Boolean(audioPlaybackRef?.current?.isPlaying);
    const fallbackLevel = speaking ? 0.24 + visemeCycleFromTime(elapsed, 8.7, 0) * 0.5 : 0;
    const lipSync = lipSyncState.current;

    if (!speaking) {
      lipSync.level = MathUtils.lerp(lipSync.level, 0, 0.28);
      lipSync.meterSeen = false;
      lipSync.lastEnergyAt = now;
    } else if (rawAudioLevel > 0.018) {
      lipSync.meterSeen = true;
      lipSync.lastEnergyAt = now;
    }

    const recentlyVoiced = now - lipSync.lastEnergyAt < 180;
    const fallbackWeight = audioPlaying && lipSync.meterSeen ? (recentlyVoiced ? 0.26 : 0.08) : 1;
    const targetSpeechLevel = speaking
      ? MathUtils.clamp(Math.max(rawAudioLevel, fallbackLevel * fallbackWeight), 0, 1)
      : 0;
    const levelEasing = targetSpeechLevel > lipSync.level ? 0.58 : 0.22;
    lipSync.level = MathUtils.lerp(lipSync.level, targetSpeechLevel, levelEasing);
    const speechLevel = lipSync.level;
    const speechProgress = getSpeechProgress({
      audioPlayback: audioPlaybackRef?.current,
      elapsedMs: now - speakingStartedAt.current,
      fallbackDurationMs: estimatedDurationMs,
      speaking,
    });
    const visemeTargets = getVisemeTargets(visemeTimeline, speechProgress, speechLevel);
    const syllablePulse = speaking
      ? Math.pow(visemeCycleFromTime(elapsed, 12.8, speechProgress * 34), 1.55) *
        (0.3 + speechLevel * 0.8) *
        SPEECH_PULSE_GAIN
      : 0;
    const idleYaw = thinking ? Math.sin(elapsed * 0.55) * 0.012 : 0;
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

    const speechGesture = speaking ? MathUtils.clamp(0.3 + speechLevel * 0.8, 0, 1) : 0;
    if (headBone) {
      headBone.rotation.x = MathUtils.lerp(
        headBone.rotation.x,
        headRestRotation.x + Math.sin(elapsed * 2.3) * 0.021 * speechGesture - 0.012 * speechGesture,
        0.08,
      );
      headBone.rotation.y = MathUtils.lerp(
        headBone.rotation.y,
        headRestRotation.y,
        0.08,
      );
      headBone.rotation.z = MathUtils.lerp(
        headBone.rotation.z,
        headRestRotation.z,
        0.08,
      );
    }
    if (neckBone) {
      neckBone.rotation.x = MathUtils.lerp(
        neckBone.rotation.x,
        neckRestRotation.x + Math.sin(elapsed * 1.5 + 1.1) * 0.01 * speechGesture,
        0.06,
      );
      neckBone.rotation.y = MathUtils.lerp(
        neckBone.rotation.y,
        neckRestRotation.y,
        0.06,
      );
    }

    const gesturePulse = speaking ? Math.pow(visemeCycleFromTime(elapsed, 2.15, speechProgress * 9.5), 2.2) : 0;
    const supportPulse = speaking ? Math.pow(visemeCycleFromTime(elapsed, 1.3, speechProgress * 5.8 + 1.4), 2.4) : 0;
    const rightGesture = speaking
      ? MathUtils.clamp((0.18 + speechLevel * 0.82) * (0.42 + gesturePulse * 0.58) * SPEECH_ARM_GESTURE_GAIN, 0, 0.36)
      : 0;
    const leftGesture = rightGesture * (0.28 + supportPulse * 0.16);
    const handWave = Math.sin(elapsed * 4.4 + speechProgress * 10) * rightGesture;

    dampBoneRotation(
      gestureRig.rightClavicle,
      gestureRigRest.rightClavicle,
      {
        x: -0.018 * rightGesture,
        y: -0.012 * rightGesture,
        z: -0.024 * rightGesture,
      },
      0.07,
    );
    dampBoneRotation(
      gestureRig.rightUpperArm,
      gestureRigRest.rightUpperArm,
      {
        x: -0.052 * rightGesture,
        y: 0.018 * handWave,
        z: 0.18 * rightGesture,
      },
      0.075,
    );
    dampBoneRotation(
      gestureRig.rightForeArm,
      gestureRigRest.rightForeArm,
      {
        x: 0.03 * rightGesture,
        y: -0.032 * handWave,
        z: 0.24 * rightGesture,
      },
      0.09,
    );
    dampBoneRotation(
      gestureRig.rightHand,
      gestureRigRest.rightHand,
      {
        x: 0.035 * rightGesture,
        y: 0.06 * handWave,
        z: -0.11 * rightGesture + 0.025 * handWave,
      },
      0.11,
    );
    dampBoneRotation(
      gestureRig.leftClavicle,
      gestureRigRest.leftClavicle,
      {
        x: -0.008 * leftGesture,
        y: 0.006 * leftGesture,
        z: 0.012 * leftGesture,
      },
      0.06,
    );
    dampBoneRotation(
      gestureRig.leftUpperArm,
      gestureRigRest.leftUpperArm,
      {
        x: -0.018 * leftGesture,
        y: -0.012 * handWave,
        z: -0.07 * leftGesture,
      },
      0.07,
    );
    dampBoneRotation(
      gestureRig.leftForeArm,
      gestureRigRest.leftForeArm,
      {
        x: 0.018 * leftGesture,
        y: 0.014 * handWave,
        z: -0.085 * leftGesture,
      },
      0.08,
    );
    dampBoneRotation(
      gestureRig.leftHand,
      gestureRigRest.leftHand,
      {
        x: 0.018 * leftGesture,
        y: -0.026 * handWave,
        z: 0.055 * leftGesture,
      },
      0.1,
    );

    const blink = Math.max(0, Math.sin(elapsed * 0.8 + blinkSeed.current) - 0.94) * 14;
    const consonantClosure = Math.max(
      visemeTargets.close,
      visemeTargets.plosive * 0.9,
      visemeTargets.dental * 0.35,
    );
    const mouthOpenTarget = speaking
      ? MathUtils.clamp(
          visemeTargets.open * SPEECH_MOUTH_GAIN + syllablePulse * 0.16 - consonantClosure * 0.04,
          0,
          0.96,
        )
      : 0.015;
    const lipPartTarget = speaking
      ? MathUtils.clamp(visemeTargets.lipPart * 1.18 + syllablePulse * 0.14 - visemeTargets.plosive * 0.16, 0, 0.92)
      : 0;
    const roundTarget = speaking ? MathUtils.clamp(visemeTargets.round * 1.12 + syllablePulse * 0.07, 0, 0.92) : 0;
    const wideTarget = speaking ? MathUtils.clamp(visemeTargets.wide * 1.1 + syllablePulse * 0.055, 0, 0.8) : 0;
    const closeTarget = speaking ? MathUtils.clamp(consonantClosure * 0.78 - mouthOpenTarget * 0.12, 0, 0.68) : 0;
    const plosiveTarget = speaking ? MathUtils.clamp(visemeTargets.plosive * 0.92, 0, 0.76) : 0;
    const dentalTarget = speaking ? MathUtils.clamp(visemeTargets.dental * 0.86, 0, 0.72) : 0;
    const bottomLipDownTarget = speaking ? MathUtils.clamp(mouthOpenTarget * 0.42 + lipPartTarget * 0.28, 0, 0.64) : 0;
    const topLipUpTarget = speaking ? MathUtils.clamp(mouthOpenTarget * 0.18 + lipPartTarget * 0.12, 0, 0.32) : 0;
    for (const mesh of morphMeshes) {
      dampInfluence(mesh, ["eyeBlinkLeft", "Eye_Blink_L"], blink);
      dampInfluence(mesh, ["eyeBlinkRight", "Eye_Blink_R"], blink);
      dampInfluence(mesh, ["eyesClosed", "Eye_Blink"], blink * 0.65);
      dampInfluence(
        mesh,
        ["mouthSmile", "Mouth_Smile"],
        0,
        0.12,
      );
      dampInfluence(
        mesh,
        ["mouthSmileLeft", "Mouth_Smile_L"],
        0,
        0.12,
      );
      dampInfluence(
        mesh,
        ["mouthSmileRight", "Mouth_Smile_R"],
        0,
        0.12,
      );
      dampInfluence(
        mesh,
        ["jawOpen", "Jaw_Open", "Mouth_Jaw_Open", "Mouth_Open", "Open", "Lip_Open"],
        mouthOpenTarget,
        0.32,
      );
      dampInfluence(
        mesh,
        ["mouthOpen", "Mouth_Lips_Open", "Mouth_Open", "Open"],
        mouthOpenTarget * 0.85,
        0.34,
      );
      dampInfluence(mesh, ["mouthClose", "Mouth_Lips_Tight", "Tight"], closeTarget, 0.3);
      dampInfluence(mesh, ["viseme_aa", "Mouth_Lips_Part", "Open", "Wide"], lipPartTarget, 0.34);
      dampInfluence(mesh, ["viseme_O", "Tight_O", "Mouth_Pucker_Open", "Mouth_Pucker"], roundTarget, 0.28);
      dampInfluence(mesh, ["viseme_I", "Mouth_Widen", "Mouth_Widen_Sides", "Wide"], wideTarget, 0.24);
      dampInfluence(mesh, ["viseme_PP", "Explosive", "Mouth_Plosive"], plosiveTarget, 0.36);
      dampInfluence(mesh, ["viseme_FF", "Dental_Lip", "Affricate"], dentalTarget, 0.34);
      dampInfluence(mesh, ["viseme_sil", "Mouth_Lips_Tuck"], 0, 0.34);
      dampInfluence(mesh, ["Mouth_Blow"], 0, 0.34);
      dampInfluence(mesh, ["Mouth_Lips_Jaw_Adjust"], 0, 0.34);
      dampInfluence(mesh, ["Mouth_Bottom_Lip_Down", "Bottom_Lip_Down"], bottomLipDownTarget, 0.3);
      dampInfluence(mesh, ["Mouth_Top_Lip_Up", "Top_Lip_Up"], topLipUpTarget, 0.28);
      dampInfluence(mesh, ["Mouth_Down"], 0, 0.34);
      dampInfluence(mesh, ["Mouth_Up"], 0, 0.34);
      dampInfluence(mesh, ["Mouth_L"], 0, 0.34);
      dampInfluence(mesh, ["Mouth_R"], 0, 0.34);
      dampInfluence(mesh, ["Mouth_Bottom_Lip_Bite", "Mouth_Top_Lip_Under"], 0, 0.34);
      dampInfluence(mesh, ["Mouth_Bottom_Lip_Trans", "Mouth_Skewer"], 0, 0.34);
      dampInfluence(
        mesh,
        ["Mouth_Snarl_Upper_L", "Mouth_Snarl_Upper_R", "Mouth_Snarl_Lower_L", "Mouth_Snarl_Lower_R"],
        0,
        0.34,
      );
      dampInfluence(mesh, ["Tongue_up", "Tongue_Raise"], 0, 0.34);
    }

    if (jawBone) {
      const jawOpen = speaking && morphMeshes.length === 0
        ? MathUtils.clamp(
            mouthOpenTarget * 0.15 + lipPartTarget * 0.035 + speechLevel * 0.025,
            0,
            0.16,
          )
        : 0;
      jawBone.rotation.x = MathUtils.lerp(jawBone.rotation.x, jawRestRotation.x + jawOpen, 0.2);
      jawBone.rotation.y = MathUtils.lerp(jawBone.rotation.y, jawRestRotation.y, 0.2);
      jawBone.rotation.z = MathUtils.lerp(jawBone.rotation.z, jawRestRotation.z, 0.2);
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
