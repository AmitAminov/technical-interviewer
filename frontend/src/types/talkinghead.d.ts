/**
 * Minimal ambient typings for @met4citizen/talkinghead (ships untyped).
 * Only the surface used by TalkingHeadAvatar.tsx is declared.
 */
declare module '@met4citizen/talkinghead' {
  export interface TalkingHeadAvatarSpec {
    url: string;
    body?: 'M' | 'F';
    avatarMood?: string;
    lipsyncLang?: string;
    baseline?: Record<string, number>;
    retarget?: Record<string, unknown>;
    modelDynamicBones?: Array<Record<string, unknown>>;
  }

  export interface SpeakAudioPayload {
    audio: AudioBuffer | ArrayBuffer | ArrayBuffer[];
    words?: string[];
    wtimes?: number[];
    wdurations?: number[];
    visemes?: string[];
    vtimes?: number[];
    vdurations?: number[];
    markers?: Array<() => void>;
    mtimes?: number[];
  }

  export class TalkingHead {
    constructor(node: HTMLElement, opt?: Record<string, unknown>);

    showAvatar(
      avatar: TalkingHeadAvatarSpec,
      onprogress?: (event: ProgressEvent) => void,
    ): Promise<unknown>;

    speakAudio(
      payload: SpeakAudioPayload,
      opt?: Record<string, unknown>,
      onsubtitles?: (subtitle: string) => void,
    ): void;

    speakMarker(onmarker: () => void): Promise<void>;

    stopSpeaking(): void;

    setMood(mood: string): void;

    lookAtCamera(t: number): void;

    start(): void;

    stop(): void;

    dispose(): void;
  }
}
