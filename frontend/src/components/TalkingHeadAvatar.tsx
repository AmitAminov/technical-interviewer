/**
 * Real-time 3D talking-head interviewer built on @met4citizen/talkinghead
 * (three.js, Ready Player Me-style GLB avatars with Oculus viseme morphs).
 *
 * - Lazily dynamic-imports the 3D stack (so jsdom tests and non-WebGL
 *   browsers never load three.js) and mounts TalkingHead into a div.
 * - Registers itself as the VoiceEngine sink: decoded HeadTTS chunk payloads
 *   ({audio: AudioBuffer, words/wtimes/wdurations, visemes/vtimes/vdurations})
 *   are streamed straight into head.speakAudio for native mouth animation; queue
 *   markers bracket onStart/onEnd. Idle blink/sway/mood come built in.
 * - Robust fallback chain: WebGL unavailable, dynamic import failure or GLB
 *   load failure → the existing SVG <Avatar> renders unchanged. A small
 *   3D/classic toggle is persisted in localStorage (default 3D when
 *   supported).
 *
 * Two photo-realistic GLBs ship offline (see public/avatars/LICENSES.md):
 * avaturn.glb (female, Avaturn) and avatarsdk.glb (male, Avatar SDK). Both
 * carry the full Oculus viseme set + ARKit blendshapes, so mouth animation works on
 * either. Faces are matched to the voice gender in lib/voice.ts (af_bella →
 * avaturn, am_fenrir → avatarsdk) and personas are differentiated by mood,
 * camera framing and photographic (soft-fill + directional key) lighting. The
 * stylised Ready-Player-Me brunette.glb is retired from the defaults — it read
 * as too cartoony — but stays in the repo for the classic toggle / legacy.
 *   Friendly             avaturn.glb    F  mood happy    upper  warm key
 *   Research professor   avaturn.glb    F  mood neutral  head   warm dim
 *   Big-tech interviewer avaturn.glb    F  mood neutral  upper  cool corporate
 *   Strict               avatarsdk.glb  M  mood neutral  head   steel key
 *   Startup CTO          avatarsdk.glb  M  mood happy    upper  warm teal
 */
import { useEffect, useRef, useState } from 'react';

import type { TalkingHead } from '@met4citizen/talkinghead';

import { voiceEngine } from '../lib/voice';
import type { InterviewerStyle } from '../lib/types';
import Avatar from './Avatar';

export interface TalkingHeadAvatarProps {
  style: InterviewerStyle;
  name: string;
  speaking: boolean;
  /** Pixel size of the (square) avatar stage. */
  size?: number;
  /** SVG fallback: word-boundary tick. */
  wordTick?: number;
  /** SVG fallback: explicit viseme-driven mouth shape (0-3). */
  mouthShape?: number | null;
}

interface Style3dConfig {
  url: string;
  body: 'M' | 'F';
  mood: string;
  cameraView: 'head' | 'upper' | 'mid' | 'full';
  lightAmbientColor: number;
  lightDirectColor: number;
  lightAmbientIntensity: number;
  /** Directional "key" light strength. Higher = more contrast/shaping, which
   *  reads as photographic rather than flat/cartoony. */
  lightDirectIntensity: number;
  baseline?: Record<string, number>;
  retarget?: Record<string, unknown>;
}

/** Avaturn rig corrections, copied from the TalkingHead repo's siteconfig.js. */
const AVATURN_EXTRAS = {
  retarget: {
    Hips: { y: 0.03 },
    Spine: { y: 0.02 },
    Spine1: { y: 0.02, z: 0.01 },
    Spine2: { y: 0.02, z: 0.01 },
    Neck: { z: 0.02, y: 0.01 },
    Head: { z: 0.02 },
    LeftShoulder: { rx: -0.5 },
    RightShoulder: { rx: -0.5 },
    scaleToHipsLevel: 1.0,
  },
  baseline: { headRotateX: -0.05, eyeBlinkLeft: 0.15, eyeBlinkRight: 0.15 },
};

const STYLE_3D: Record<InterviewerStyle, Style3dConfig> = {
  // Female voice (af_bella) → Avaturn photo-realistic face.
  Friendly: {
    url: '/avatars/avaturn.glb',
    body: 'F',
    mood: 'happy',
    cameraView: 'upper',
    lightAmbientColor: 0xf3ece2,
    lightAmbientIntensity: 1.25,
    lightDirectColor: 0xffe6c6,
    lightDirectIntensity: 32,
    ...AVATURN_EXTRAS,
  },
  'Research professor': {
    url: '/avatars/avaturn.glb',
    body: 'F',
    mood: 'neutral',
    cameraView: 'head',
    lightAmbientColor: 0xefe8dc,
    lightAmbientIntensity: 1.05,
    lightDirectColor: 0xe9d6b8,
    lightDirectIntensity: 26,
    ...AVATURN_EXTRAS,
  },
  'Big-tech interviewer': {
    url: '/avatars/avaturn.glb',
    body: 'F',
    mood: 'neutral',
    cameraView: 'upper',
    lightAmbientColor: 0xe8ecf4,
    lightAmbientIntensity: 1.2,
    lightDirectColor: 0xd2ddf2,
    lightDirectIntensity: 30,
    ...AVATURN_EXTRAS,
  },
  // Male voice (am_fenrir) → Avatar SDK photo-realistic face. Standard RPM
  // skeleton + Oculus visemes, so no retarget needed (verified from the GLB).
  Strict: {
    url: '/avatars/avatarsdk.glb',
    body: 'M',
    mood: 'neutral',
    cameraView: 'head',
    lightAmbientColor: 0xe6e9f0,
    lightAmbientIntensity: 1.05,
    lightDirectColor: 0xc6d0e2,
    lightDirectIntensity: 30,
  },
  'Startup CTO': {
    url: '/avatars/avatarsdk.glb',
    body: 'M',
    mood: 'happy',
    cameraView: 'upper',
    lightAmbientColor: 0xe6f1ec,
    lightAmbientIntensity: 1.25,
    lightDirectColor: 0xc4e4d6,
    lightDirectIntensity: 32,
  },
};

export function webglSupported(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

type HeadStatus = 'loading' | 'ready' | 'failed';

export default function TalkingHeadAvatar({
  style,
  name,
  speaking,
  size = 300,
  wordTick,
  mouthShape,
}: TalkingHeadAvatarProps) {
  const [supported] = useState<boolean>(() => webglSupported());
  const [status, setStatus] = useState<HeadStatus>('loading');
  const [progress, setProgress] = useState(0);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const headRef = useRef<TalkingHead | null>(null);

  // The interview always renders the real-time 3D talking head; if WebGL is
  // unavailable or the 3D stack fails to load, it falls back to the SVG avatar.
  const use3d = supported;

  useEffect(() => {
    if (!use3d) return undefined;
    let disposed = false;
    setStatus('loading');
    setProgress(0);

    const config = STYLE_3D[style] ?? STYLE_3D.Friendly;
    (async () => {
      try {
        const { TalkingHead: TalkingHeadCtor } = await import('@met4citizen/talkinghead');
        const node = containerRef.current;
        if (disposed || !node) return;
        // Short stages (small/landscape-cramped viewports) crop 'upper'
        // framing at the neck — fall back to a head close-up so the face
        // stays visible.
        const shortStage = node.clientHeight > 0 && node.clientHeight < 300;
        const cameraView =
          shortStage && config.cameraView === 'upper' ? 'head' : config.cameraView;
        const head = new TalkingHeadCtor(node, {
          // TTS goes through VoiceEngine → speakAudio; the endpoint is never
          // called but the option must be non-empty for the constructor.
          ttsEndpoint: '/api/voice/tts',
          // HeadTTS always supplies viseme timelines, so the text→viseme
          // lipsync modules are unnecessary — and skipping them avoids a
          // runtime dynamic import ('./lipsync-en.mjs') Vite cannot bundle.
          lipsyncModules: [],
          lipsyncLang: 'en',
          cameraView,
          cameraRotateEnable: false,
          cameraZoomEnable: false,
          avatarMood: config.mood,
          lightAmbientColor: config.lightAmbientColor,
          lightAmbientIntensity: config.lightAmbientIntensity,
          lightDirectColor: config.lightDirectColor,
          lightDirectIntensity: config.lightDirectIntensity,
          modelPixelRatio: window.devicePixelRatio || 1,
        });
        headRef.current = head;
        await head.showAvatar(
          {
            url: config.url,
            body: config.body,
            avatarMood: config.mood,
            lipsyncLang: 'en',
            ...(config.baseline ? { baseline: config.baseline } : {}),
            ...(config.retarget ? { retarget: config.retarget } : {}),
          },
          (event) => {
            if (event.lengthComputable && event.total > 0) {
              setProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
            }
          },
        );
        if (disposed) {
          head.dispose();
          headRef.current = null;
          return;
        }
        setStatus('ready');
        // Stream HeadTTS payloads natively: TalkingHead plays the audio and
        // animates visemes; markers give VoiceEngine start/end callbacks.
        let wordCounter = 0;
        voiceEngine.setSink({
          speak: (chunk, onWord) => {
            wordCounter = 0;
            head.speakAudio(chunk, {}, () => {
              onWord(wordCounter, chunk.words);
              wordCounter += 1;
            });
          },
          marker: (callback) => {
            void head.speakMarker(callback);
          },
          interrupt: () => head.stopSpeaking(),
        });
      } catch (error) {
        // Import failed / WebGL context refused / GLB fetch failed → SVG.
        console.warn('3D avatar unavailable, falling back to SVG:', error);
        if (!disposed) setStatus('failed');
      }
    })();

    return () => {
      disposed = true;
      voiceEngine.setSink(null);
      const head = headRef.current;
      headRef.current = null;
      if (head) {
        try {
          head.stopSpeaking();
        } catch {
          /* never spoke */
        }
        try {
          head.dispose();
        } catch {
          /* already gone */
        }
      }
      const node = containerRef.current;
      if (node) node.innerHTML = '';
    };
  }, [use3d, style]);

  if (!use3d || status === 'failed') {
    return (
      <div className="relative inline-block" data-testid="avatar-svg-stage">
        <Avatar
          style={style}
          speaking={speaking}
          name={name}
          size={size}
          wordTick={wordTick}
          mouthShape={mouthShape}
        />
      </div>
    );
  }

  return (
    <div
      className="relative min-h-0 w-full flex-1"
      style={{ maxWidth: size * 2, maxHeight: size * 1.3 }}
      data-testid="avatar-3d-stage"
    >
      <div ref={containerRef} className="h-full w-full overflow-hidden rounded-2xl" />
      {status === 'loading' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-slate-400">
          <span className="spinner h-6 w-6" aria-hidden="true" />
          <p className="text-xs" data-testid="avatar-3d-loading">
            Loading 3D interviewer… {progress > 0 ? `${progress}%` : ''}
          </p>
        </div>
      )}
      {speaking && status === 'ready' && (
        <span
          data-testid="speaking-dot"
          className="absolute bottom-3 left-3 h-2.5 w-2.5 rounded-full bg-indigo-400 animate-pulse"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
