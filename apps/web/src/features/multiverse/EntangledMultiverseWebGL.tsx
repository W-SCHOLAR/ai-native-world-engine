import { useEffect, useRef } from "react";

export type MultiverseWorldRegion = {
  id: string;
  centerX: number;
  centerY: number;
  width: number;
  height: number;
  accent?: string;
};

type EntangledMultiverseWebGLProps = {
  imageUrl: string;
  worlds: MultiverseWorldRegion[];
  activeId: string | null;
  onHoverWorld: (id: string | null) => void;
  onSelectWorld: (id: string) => void;
};

type HitMask = { width: number; height: number; pixels: Uint8ClampedArray };

const IMAGE_ASPECT = 1672 / 941;
const MASK_ROOT = "/assets/multiverse/masks";

const VERTEX_SHADER = `
  varying vec2 vUv;

  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const FRAGMENT_SHADER = `
  uniform sampler2D uImage;
  uniform sampler2D uMask;
  uniform vec2 uResolution;
  uniform vec2 uFocus;
  uniform vec2 uWorldSize;
  uniform vec3 uAccent;
  uniform float uStrength;
  uniform float uTime;
  varying vec2 vUv;

  float hash21(vec2 point) {
    point = fract(point * vec2(123.34, 456.21));
    point += dot(point, point + 45.32);
    return fract(point.x * point.y);
  }

  vec2 coverUv(vec2 screenUv) {
    float canvasAspect = uResolution.x / max(uResolution.y, 1.0);
    vec2 imageUv = screenUv;
    if (canvasAspect > ${IMAGE_ASPECT.toFixed(8)}) {
      imageUv.y = (screenUv.y - 0.5) * (${IMAGE_ASPECT.toFixed(8)} / canvasAspect) + 0.5;
    } else {
      imageUv.x = (screenUv.x - 0.5) * (canvasAspect / ${IMAGE_ASPECT.toFixed(8)}) + 0.5;
    }
    return imageUv;
  }

  void main() {
    vec2 imageUv = coverUv(vUv);
    float signedDistance = (texture2D(uMask, imageUv).r - 0.5) * 2.0;
    float edgeDistance = abs(signedDistance);
    float seam = 1.0 - smoothstep(0.035, 0.13, edgeDistance);
    float outsideMask = 1.0 - step(0.0, signedDistance);
    float energyBand = smoothstep(0.08, 0.2, edgeDistance)
      * (1.0 - smoothstep(0.22, 0.48, edgeDistance))
      * outsideMask;
    float glow = (1.0 - smoothstep(0.16, 0.82, edgeDistance)) * outsideMask;
    float inside = smoothstep(0.02, 0.2, signedDistance);

    vec2 portalPoint = (imageUv - uFocus) / max(uWorldSize, vec2(0.01));
    float radius = length(portalPoint);
    float angle = atan(portalPoint.y, portalPoint.x);
    float energySegments = smoothstep(-0.2, 0.38,
      sin(angle * 4.0 + uTime * 0.65) * 0.62
      + sin(angle * 9.0 - uTime * 0.38) * 0.38);
    float outside = max(radius - 0.92, 0.0);
    float primaryCrack = pow(1.0 - abs(sin(angle * 9.0 + sin(angle * 3.0) * 1.2)), 32.0);
    float secondaryCrack = pow(1.0 - abs(sin(angle * 15.0 - 1.1)), 46.0) * 0.42;
    float cracks = max(primaryCrack, secondaryCrack)
      * smoothstep(0.03, 0.11, outside)
      * (1.0 - smoothstep(0.18, 0.52, outside));

    float verticalDoor = 1.0 - smoothstep(0.56, 0.94, abs(portalPoint.y));
    float tearWobble = sin(portalPoint.y * 19.0 + uTime * 0.9) * 0.012
      + sin(portalPoint.y * 37.0 - uTime * 0.53) * 0.005;
    float opening = mix(0.008, 0.062, smoothstep(0.0, 1.0, uStrength));
    opening *= 0.72 + (1.0 - abs(portalPoint.y)) * 0.34;
    float doorDistance = abs(portalPoint.x + tearWobble) - opening;
    float doorVoid = (1.0 - smoothstep(0.0, 0.022, doorDistance)) * verticalDoor * inside;
    float doorEdge = smoothstep(0.012, 0.028, abs(doorDistance))
      * (1.0 - smoothstep(0.03, 0.068, abs(doorDistance)))
      * verticalDoor * inside;
    vec2 refractionOffset = vec2(
      sign(portalPoint.x + tearWobble) * 0.007 * (1.0 - min(abs(portalPoint.y), 1.0)),
      sin(portalPoint.y * 24.0 + uTime * 0.7) * 0.0016
    );
    vec3 refractedColor = texture2D(uImage, imageUv + refractionOffset).rgb;

    vec2 starCell = floor(imageUv * vec2(940.0, 530.0));
    float starNoise = hash21(starCell);
    float stars = step(0.996, starNoise) * inside;
    stars *= 0.52 + sin(uTime * (1.0 + hash21(starCell + 3.0)) + starNoise * 20.0) * 0.38;
    float doorStars = step(0.982, starNoise) * doorVoid;

    float breath = 0.82 + sin(uTime * 1.3) * 0.08;
    vec3 coolEnergy = mix(vec3(0.22, 0.34, 0.88), uAccent, 0.38);
    vec3 effectColor = coolEnergy * glow * 0.16;
    effectColor += uAccent * energyBand * energySegments * breath * 0.94;
    effectColor += mix(vec3(0.42, 0.54, 1.0), uAccent, 0.45) * cracks * 0.56;
    effectColor += vec3(0.72, 0.82, 1.0) * stars * 1.2;
    effectColor = mix(effectColor, refractedColor + mix(vec3(0.16, 0.24, 0.7), uAccent, 0.4) * 0.22, doorEdge * 0.72);
    effectColor += mix(vec3(0.5, 0.62, 1.0), uAccent, 0.36) * doorEdge * 0.62;
    effectColor += vec3(0.78, 0.88, 1.0) * doorStars * 1.35;

    float effectAlpha = max(glow * energySegments * 0.18, energyBand * energySegments * 0.78);
    effectAlpha = max(effectAlpha, cracks * 0.48);
    effectAlpha = max(effectAlpha, stars * 0.82);
    effectAlpha = max(effectAlpha, doorEdge * 0.88);
    effectColor = mix(effectColor, vec3(0.002, 0.003, 0.009), seam * 0.82);
    effectAlpha = max(effectAlpha, seam * 0.72);
    effectColor = mix(effectColor, vec3(0.001, 0.002, 0.008), doorVoid * 0.94);
    effectAlpha = max(effectAlpha, doorVoid * 0.82);
    gl_FragColor = vec4(effectColor, effectAlpha * uStrength);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

function coverUvForPointer(x: number, y: number, width: number, height: number) {
  const canvasAspect = width / Math.max(height, 1);
  let imageX = x;
  let imageY = y;
  if (canvasAspect > IMAGE_ASPECT) {
    imageY = (y - .5) * (IMAGE_ASPECT / canvasAspect) + .5;
  } else {
    imageX = (x - .5) * (canvasAspect / IMAGE_ASPECT) + .5;
  }
  return { x: imageX, y: imageY };
}

function fallbackWorldAtUv(uv: { x: number; y: number }, worlds: MultiverseWorldRegion[]) {
  let nearest: { id: string; score: number } | null = null;
  for (const world of worlds) {
    const score = Math.hypot(
      (uv.x - world.centerX / 100) / Math.max(world.width / 200, .05),
      (uv.y - (1 - world.centerY / 100)) / Math.max(world.height / 200, .05),
    );
    if (score <= 1.05 && (!nearest || score < nearest.score)) nearest = { id: world.id, score };
  }
  return nearest?.id ?? null;
}

function maskedWorldAtUv(uv: { x: number; y: number }, worlds: MultiverseWorldRegion[], masks: Map<string, HitMask>) {
  let best: { id: string; value: number } | null = null;
  for (const world of worlds) {
    const mask = masks.get(world.id);
    if (!mask) continue;
    const x = Math.max(0, Math.min(mask.width - 1, Math.round(uv.x * (mask.width - 1))));
    const y = Math.max(0, Math.min(mask.height - 1, Math.round((1 - uv.y) * (mask.height - 1))));
    const value = mask.pixels[(y * mask.width + x) * 4];
    if (value > 132 && (!best || value > best.value)) best = { id: world.id, value };
  }
  return best?.id ?? fallbackWorldAtUv(uv, worlds);
}

export function EntangledMultiverseWebGL({ imageUrl, worlds, activeId, onHoverWorld, onSelectWorld }: EntangledMultiverseWebGLProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const activeIdRef = useRef(activeId);
  const hoverCallbackRef = useRef(onHoverWorld);
  const selectCallbackRef = useRef(onSelectWorld);
  activeIdRef.current = activeId;
  hoverCallbackRef.current = onHoverWorld;
  selectCallbackRef.current = onSelectWorld;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const canvasElement = canvas;
    let disposed = false;
    let frame = 0;
    let cleanup = () => {};

    void import("three").then((THREE) => {
      if (disposed) return;
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const renderer = new THREE.WebGLRenderer({
        canvas: canvasElement,
        antialias: false,
        alpha: true,
        premultipliedAlpha: false,
        powerPreference: "high-performance",
      });
      const pixelRatio = Math.min(window.devicePixelRatio, 1.5);
      renderer.setPixelRatio(pixelRatio);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.setClearColor(0x000000, 0);
      const scene = new THREE.Scene();
      const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      const textureLoader = new THREE.TextureLoader();
      const imageTexture = textureLoader.load(imageUrl);
      imageTexture.colorSpace = THREE.SRGBColorSpace;
      imageTexture.minFilter = THREE.LinearFilter;
      imageTexture.magFilter = THREE.LinearFilter;
      const maskTextures = new Map<string, InstanceType<typeof THREE.Texture>>();
      const hitMasks = new Map<string, HitMask>();
      worlds.forEach((world) => {
        const url = `${MASK_ROOT}/${world.id}.png`;
        const texture = textureLoader.load(url);
        texture.colorSpace = THREE.NoColorSpace;
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;
        maskTextures.set(world.id, texture);

        const image = new Image();
        image.onload = () => {
          const hitCanvas = document.createElement("canvas");
          hitCanvas.width = image.naturalWidth;
          hitCanvas.height = image.naturalHeight;
          const context = hitCanvas.getContext("2d", { willReadFrequently: true });
          context?.drawImage(image, 0, 0);
          if (context) hitMasks.set(world.id, { width: hitCanvas.width, height: hitCanvas.height, pixels: context.getImageData(0, 0, hitCanvas.width, hitCanvas.height).data });
        };
        image.src = url;
      });

      const uniforms = {
        uImage: { value: imageTexture },
        uMask: { value: maskTextures.get(worlds[0].id) },
        uResolution: { value: new THREE.Vector2(1, 1) },
        uFocus: { value: new THREE.Vector2(.5, .5) },
        uWorldSize: { value: new THREE.Vector2(.15, .15) },
        uAccent: { value: new THREE.Color(0x8f7dff) },
        uStrength: { value: 0 },
        uTime: { value: 0 },
      };
      const geometry = new THREE.PlaneGeometry(2, 2);
      const material = new THREE.ShaderMaterial({
        uniforms,
        vertexShader: VERTEX_SHADER,
        fragmentShader: FRAGMENT_SHADER,
        transparent: true,
        depthWrite: false,
        blending: THREE.NormalBlending,
      });
      scene.add(new THREE.Mesh(geometry, material));
      const clock = new THREE.Clock();
      let hoveredId: string | null = null;
      let renderedId: string | null = null;

      function resize() {
        const width = Math.max(canvasElement.clientWidth, 1);
        const height = Math.max(canvasElement.clientHeight, 1);
        if (canvasElement.width !== Math.round(width * pixelRatio) || canvasElement.height !== Math.round(height * pixelRatio)) {
          renderer.setSize(width, height, false);
          uniforms.uResolution.value.set(width, height);
        }
      }

      function hitTest(event: PointerEvent) {
        const bounds = canvasElement.getBoundingClientRect();
        const screenX = (event.clientX - bounds.left) / bounds.width;
        const screenY = 1 - (event.clientY - bounds.top) / bounds.height;
        const imageUv = coverUvForPointer(screenX, screenY, bounds.width, bounds.height);
        const nextId = maskedWorldAtUv(imageUv, worlds, hitMasks);
        if (nextId !== hoveredId) {
          hoveredId = nextId;
          hoverCallbackRef.current(nextId);
        }
        return nextId;
      }

      function onPointerMove(event: PointerEvent) { hitTest(event); }
      function onPointerLeave() {
        hoveredId = null;
        hoverCallbackRef.current(null);
      }
      function onPointerUp(event: PointerEvent) {
        const selectedId = hitTest(event);
        if (selectedId) selectCallbackRef.current(selectedId);
      }
      canvasElement.addEventListener("pointermove", onPointerMove);
      canvasElement.addEventListener("pointerleave", onPointerLeave);
      canvasElement.addEventListener("pointerup", onPointerUp);

      function render() {
        resize();
        const world = worlds.find((candidate) => candidate.id === activeIdRef.current) ?? null;
        if (world && world.id !== renderedId) {
          renderedId = world.id;
          uniforms.uStrength.value = 0;
          uniforms.uMask.value = maskTextures.get(world.id);
          uniforms.uFocus.value.set(world.centerX / 100, 1 - world.centerY / 100);
          uniforms.uWorldSize.value.set(world.width / 200, world.height / 200);
          uniforms.uAccent.value.set(world.accent ?? "#8f7dff");
        }
        const targetStrength = world ? 1 : 0;
        uniforms.uStrength.value += (targetStrength - uniforms.uStrength.value) * (reducedMotion ? 1 : .085);
        if (!world && uniforms.uStrength.value < .01) renderedId = null;
        uniforms.uTime.value = reducedMotion ? 0 : clock.getElapsedTime();
        renderer.render(scene, camera);
        frame = window.requestAnimationFrame(render);
      }

      render();
      canvasElement.dataset.webgl = "ready";
      cleanup = () => {
        window.cancelAnimationFrame(frame);
        canvasElement.removeEventListener("pointermove", onPointerMove);
        canvasElement.removeEventListener("pointerleave", onPointerLeave);
        canvasElement.removeEventListener("pointerup", onPointerUp);
        geometry.dispose();
        material.dispose();
        maskTextures.forEach((texture) => texture.dispose());
        imageTexture.dispose();
        renderer.dispose();
      };
    }).catch(() => {
      canvasElement.dataset.webgl = "unavailable";
    });

    return () => {
      disposed = true;
      cleanup();
    };
  }, [imageUrl, worlds]);

  return <canvas ref={canvasRef} className="multiverse-webgl" aria-label="十个世界与空间撕裂入口" />;
}
