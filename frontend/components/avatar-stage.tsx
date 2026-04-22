"use client";

import { Suspense, useEffect, useMemo, useRef } from "react";

import { Environment, Html, useAnimations, useGLTF } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Box3, Group, MathUtils, Mesh, Object3D, Vector3 } from "three";
import { clone } from "three/examples/jsm/utils/SkeletonUtils.js";

const MODEL_PATH = "/avatars/model2.gltf";
const AVATAR_CAMERA_DISTANCE = 3.68;
const AVATAR_CAMERA_FOCUS_Y = 1.02;
const AVATAR_MODEL_LIFT = 0.82;
const AVATAR_TARGET_EYE_LINE = 1.1;

type PreparedAvatar = {
  scene: Object3D;
  scale: number;
  eyeHeight: number;
};

type MorphMesh = Mesh & {
  morphTargetDictionary?: Record<string, number>;
  morphTargetInfluences?: number[];
};

function AvatarFallback() {
  return (
    <div className="avatar-fallback">
      <p>3D avatar yukleniyor...</p>
    </div>
  );
}

function dampInfluence(
  mesh: MorphMesh,
  name: string,
  target: number,
  easing = 0.18,
) {
  const dictionary = mesh.morphTargetDictionary;
  const influences = mesh.morphTargetInfluences;
  const index = dictionary?.[name];

  if (index === undefined || !influences) {
    return;
  }

  influences[index] = MathUtils.lerp(influences[index] ?? 0, target, easing);
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

function AvatarModel({ speakingUntil }: { speakingUntil: React.RefObject<number> }) {
  const root = useRef<Group>(null);
  const { scene, animations } = useGLTF(MODEL_PATH);
  const prepared = useMemo<PreparedAvatar>(() => {
    const clonedScene = clone(scene);
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

    clonedScene.position.x -= focusPoint.x;
    clonedScene.position.y -= bounds.min.y;
    clonedScene.position.z -= focusPoint.z;

    const width = Math.max(size.x, size.z, 1);
    const height = Math.max(size.y, 1);
    const baseScale = Math.min(2.15 / height, 1.7 / width);
    const portraitScale = baseScale * 1.84;
    const eyeHeight = Math.max(focusPoint.y - bounds.min.y, height * 0.78);

    return { scene: clonedScene, scale: portraitScale, eyeHeight };
  }, [scene]);
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

  useEffect(() => {
    const preferredAction =
      actions?.idle ??
      actions?.happy ??
      Object.values(actions ?? {}).find(Boolean);

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
    const speaking = state.clock.elapsedTime * 1000 < 0 ? false : performance.now() < speakingUntil.current;
    const idleYaw = Math.sin(elapsed * 0.55) * 0.08;
    const idlePitch = Math.sin(elapsed * 0.35) * 0.03;
    const speakingBob = speaking ? Math.sin(elapsed * 7.2) * 0.035 : 0;
    const baseY = AVATAR_TARGET_EYE_LINE - (prepared.eyeHeight * prepared.scale);

    root.current.rotation.y = MathUtils.lerp(
      root.current.rotation.y,
      idleYaw,
      0.06,
    );
    root.current.rotation.x = MathUtils.lerp(root.current.rotation.x, idlePitch + speakingBob, 0.08);
    root.current.position.y = MathUtils.lerp(
      root.current.position.y,
      baseY + AVATAR_MODEL_LIFT + (speaking ? -0.05 : 0),
      0.08,
    );
    root.current.position.z = MathUtils.lerp(root.current.position.z, speaking ? 0.03 : 0, 0.08);

    const blink = Math.max(0, Math.sin(elapsed * 0.8 + blinkSeed.current) - 0.94) * 14;
    const visemeCycle = (Math.sin(elapsed * 10.6) + 1) * 0.5;
    const altVisemeCycle = (Math.sin(elapsed * 8.4 + 1.4) + 1) * 0.5;

    for (const mesh of morphMeshes) {
      dampInfluence(mesh, "eyeBlinkLeft", blink);
      dampInfluence(mesh, "eyeBlinkRight", blink);
      dampInfluence(mesh, "mouthSmile", speaking ? 0.12 : 0.05, 0.12);
      dampInfluence(mesh, "mouthSmileLeft", speaking ? 0.1 : 0.04, 0.12);
      dampInfluence(mesh, "mouthSmileRight", speaking ? 0.1 : 0.04, 0.12);
      dampInfluence(mesh, "jawOpen", speaking ? 0.08 + visemeCycle * 0.3 : 0, 0.22);
      dampInfluence(mesh, "mouthOpen", speaking ? 0.12 + altVisemeCycle * 0.26 : 0.02, 0.24);
      dampInfluence(mesh, "mouthClose", speaking ? 0.04 : 0.1, 0.18);
      dampInfluence(mesh, "viseme_aa", speaking ? 0.1 + visemeCycle * 0.6 : 0, 0.22);
      dampInfluence(mesh, "viseme_O", speaking ? altVisemeCycle * 0.42 : 0, 0.2);
      dampInfluence(mesh, "viseme_I", speaking ? (1 - visemeCycle) * 0.18 : 0, 0.18);
      dampInfluence(mesh, "viseme_sil", speaking ? 0.02 : 0.16, 0.16);
    }
  });

  return (
    <group ref={root}>
      <primitive object={prepared.scene} scale={prepared.scale} />
    </group>
  );
}

function HeadshotCamera({ focusY }: { focusY: number }) {
  const { camera } = useThree();

  useEffect(() => {
    camera.position.set(0, focusY, AVATAR_CAMERA_DISTANCE);
    camera.lookAt(0, focusY, 0);
    camera.updateProjectionMatrix();
  }, [camera, focusY]);

  return null;
}

export function AvatarStage({ speechKey }: { speechKey: string | null }) {
  const speakingUntil = useRef(0);
  const focusY = AVATAR_CAMERA_FOCUS_Y;

  useEffect(() => {
    if (!speechKey) {
      return;
    }

    speakingUntil.current = performance.now() + 4200;
  }, [speechKey]);

  return (
    <div className="avatar-stage avatar-stage-portrait">
      <Canvas
        camera={{ position: [0, focusY, AVATAR_CAMERA_DISTANCE], fov: 28, near: 0.01, far: 20 }}
        dpr={[1, 1.5]}
        fallback={<AvatarFallback />}
      >
        <HeadshotCamera focusY={focusY} />
        <color attach="background" args={["#08131b"]} />
        <fog attach="fog" args={["#08131b", 2.8, 6.2]} />
        <ambientLight intensity={1.65} />
        <directionalLight position={[2.5, 1.8, 3.2]} intensity={2.2} />
        <directionalLight position={[-2.2, 0.5, 2.4]} intensity={1.1} color="#67d9ff" />
        <spotLight position={[0, 2.8, 3.4]} angle={0.42} penumbra={0.7} intensity={28} />
        <Suspense
          fallback={
            <Html center>
              <div className="avatar-loader">Model hazirlaniyor...</div>
            </Html>
          }
        >
          <AvatarModel speakingUntil={speakingUntil} />
          <Environment preset="studio" />
        </Suspense>
      </Canvas>
    </div>
  );
}

useGLTF.preload(MODEL_PATH);
