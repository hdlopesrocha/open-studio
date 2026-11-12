import type { FileInfo, Job, SystemStatus } from "./types";

export { DEMO } from "./types";

const now = Date.now();
const iso = (minutesAgo: number) => new Date(now - minutesAgo * 60000).toISOString();

export const demoStatus: SystemStatus = {
  app: { name: "Open Studio", version: "1.0.0", uptime_seconds: 18432 },
  setup_required: false,
  services: [
    ["chat", "Chat", "core"],
    ["music", "Music", "create"],
    ["dj", "DJ Studio", "create"],
    ["video", "Video", "create"],
    ["voice", "Voice", "create"],
    ["srt", "Subtitles", "create"],
    ["imagegen", "Images", "create"],
    ["docs", "Documents", "text"],
    ["translation", "Translate", "text"],
    ["summary", "Summary", "text"],
    ["pdf", "PDF", "text"],
    ["ffmpeg", "FFmpeg", "tools"],
    ["ytdlp", "yt-dlp", "tools"],
    ["qvac", "QVAC", "create"],
    ["files", "Files", "core"],
    ["jobs", "Jobs", "core"],
    ["llm", "LLM", "core"],
  ].map(([name, label, category], index) => ({
    name: name as string,
    label: label as string,
    category: category as string,
    online: true,
    status: "ok",
    version: "1.0.0",
    latency_ms: 6 + index * 3,
    detail: name as string,
  })),
  online: 17,
  total: 17,
  queues: {
    components: [
      ["music", 1, 0, 0],
      ["dj", 1, 0, 0],
      ["video", 2, 1, 1],
      ["voice", 1, 0, 1],
      ["srt", 1, 0, 0],
      ["imagegen", 1, 1, 1],
      ["docs", 2, 0, 0],
      ["translation", 2, 0, 0],
      ["summary", 1, 0, 0],
      ["pdf", 2, 0, 0],
      ["ffmpeg", 2, 0, 0],
      ["ytdlp", 2, 0, 0],
      ["qvac", 1, 0, 0],
      ["models", 1, 0, 0],
      ["llm", 2, 0, 0],
    ].map(([component, concurrency, queued, running]) => ({
      component: component as string,
      concurrency: concurrency as number,
      queued: queued as number,
      running: running as number,
      completed: 14,
      failed: 0,
    })),
  },
  storage: { root: "/data/files", total: 512 * 1024 ** 3, used: 184 * 1024 ** 3, free: 328 * 1024 ** 3, free_label: "328 GB" },
  system: { cpu_percent: 34, cpu_count: 16, memory_total: 32 * 1024 ** 3, memory_used: 14 * 1024 ** 3, memory_percent: 44, gpu: null },
};

export const demoJobs: Job[] = [
  {
    id: "job_9f2a71c3",
    component: "video",
    action: "full",
    title: "Atravessar a Noite — full production",
    status: "running",
    stage: "animation",
    message: "Animating scene 11 of 18 with FFmpeg",
    progress: 67.4,
    params: { project_id: "atravessar-noite" },
    result: null,
    error: null,
    warnings: ["Scene 04 re-used the procedural fallback for image generation."],
    artifacts: [],
    cancel_requested: false,
    attempts: 1,
    created_at: iso(9),
    started_at: iso(9),
    finished_at: null,
    updated_at: iso(0),
  },
  {
    id: "job_41bd03ab",
    component: "imagegen",
    action: "generate",
    title: "Album cover — porcelain city at dusk",
    status: "running",
    stage: "diffusion",
    message: "Sampling step 21/30",
    progress: 72,
    params: {},
    result: null,
    error: null,
    warnings: [],
    artifacts: [],
    cancel_requested: false,
    attempts: 1,
    created_at: iso(2),
    started_at: iso(2),
    finished_at: null,
    updated_at: iso(0),
  },
  {
    id: "job_78a2b901",
    component: "music",
    action: "generate",
    title: "Nocturno — full take, 2 variations",
    status: "queued",
    stage: "Queued",
    message: "Waiting for the music worker.",
    progress: 0,
    params: {},
    result: null,
    error: null,
    warnings: [],
    artifacts: [],
    cancel_requested: false,
    attempts: 1,
    created_at: iso(1),
    started_at: null,
    finished_at: null,
    updated_at: iso(1),
  },
  {
    id: "job_2c7e1a55",
    component: "voice",
    action: "tts",
    title: "Chapter 03 — narration, 18 sentences",
    status: "completed",
    stage: "Complete",
    message: "18 sentences rendered with OmniVoice.",
    progress: 100,
    params: {},
    result: {
      files: [
        { path: "voice/outputs/2c7e1a55/chapter-03.mp3", name: "chapter-03.mp3", kind: "audio", size: 8421934 },
        { path: "voice/outputs/2c7e1a55/timeline.json", name: "timeline.json", kind: "document", size: 2211 },
      ],
    },
    error: null,
    warnings: [],
    artifacts: [
      { path: "voice/outputs/2c7e1a55/chapter-03.mp3", name: "chapter-03.mp3", kind: "audio", mime: "audio/mpeg", size: 8421934 },
    ],
    cancel_requested: false,
    attempts: 1,
    created_at: iso(44),
    started_at: iso(44),
    finished_at: iso(38),
    updated_at: iso(38),
  },
  {
    id: "job_67c9de20",
    component: "srt",
    action: "align",
    title: "Nocturno — lyrics to SRT alignment",
    status: "completed",
    stage: "Complete",
    message: "42 cues aligned with 96% confidence.",
    progress: 100,
    params: {},
    result: {
      files: [{ path: "subtitles/67c9de20/nocturno.srt", name: "nocturno.srt", kind: "subtitle", size: 3120 }],
      cues: 42,
    },
    error: null,
    warnings: [],
    artifacts: [{ path: "subtitles/67c9de20/nocturno.srt", name: "nocturno.srt", kind: "subtitle", mime: "application/x-subrip", size: 3120 }],
    cancel_requested: false,
    attempts: 1,
    created_at: iso(70),
    started_at: iso(70),
    finished_at: iso(68),
    updated_at: iso(68),
  },
  {
    id: "job_33af9e88",
    component: "docs",
    action: "pipeline",
    title: "Relatório anual — translate, summarize, narrate",
    status: "completed",
    stage: "Complete",
    message: "Document pipeline finished.",
    progress: 100,
    params: {},
    result: {
      files: [
        { path: "documents/33af9e88/summary.txt", name: "summary.txt", kind: "document", size: 4201 },
        { path: "documents/33af9e88/audio.mp3", name: "audio.mp3", kind: "audio", size: 16200432 },
        { path: "documents/33af9e88/output.zip", name: "output.zip", kind: "archive", size: 16233002 },
      ],
    },
    error: null,
    warnings: [],
    artifacts: [
      { path: "documents/33af9e88/summary.txt", name: "summary.txt", kind: "document", mime: "text/plain", size: 4201 },
      { path: "documents/33af9e88/audio.mp3", name: "audio.mp3", kind: "audio", mime: "audio/mpeg", size: 16200432 },
    ],
    cancel_requested: false,
    attempts: 1,
    created_at: iso(105),
    started_at: iso(105),
    finished_at: iso(92),
    updated_at: iso(92),
  },
  {
    id: "job_54b0ca12",
    component: "ffmpeg",
    action: "extract_audio",
    title: "Extract audio · concert-master.mkv → FLAC",
    status: "failed",
    stage: "Failed",
    message: "Input has no audio stream",
    progress: 12,
    params: {},
    result: null,
    error: "ffmpeg: Stream map '0:a:0' matches no streams.",
    warnings: [],
    artifacts: [],
    cancel_requested: false,
    attempts: 1,
    created_at: iso(140),
    started_at: iso(140),
    finished_at: iso(139),
    updated_at: iso(139),
  },
  {
    id: "job_10cd72f4",
    component: "ytdlp",
    action: "download",
    title: "Field recording playlist · 3 videos",
    status: "canceled",
    stage: "Cancelled",
    message: "Cancelled by the user.",
    progress: 28,
    params: {},
    result: null,
    error: null,
    warnings: [],
    artifacts: [],
    cancel_requested: true,
    attempts: 1,
    created_at: iso(190),
    started_at: iso(190),
    finished_at: iso(186),
    updated_at: iso(186),
  },
];

const file = (path: string, size: number, kind: string, modified = iso(30)): FileInfo => ({
  name: path.split("/").pop() || path,
  path,
  is_dir: false,
  size,
  size_label: size > 1024 ** 2 ? `${(size / 1024 ** 2).toFixed(1)} MB` : `${(size / 1024).toFixed(0)} KB`,
  modified,
  mime: kind === "audio" ? "audio/mpeg" : kind === "image" ? "image/png" : "application/octet-stream",
  kind,
  url: `/api/files/raw/${path}`,
});

export const demoFiles: FileInfo[] = [
  { ...file("music/nocturno/takes", 0, "folder"), is_dir: true, children: 12, kind: "folder", mime: "inode/directory" },
  { ...file("video/atravessar-noite/output", 0, "folder"), is_dir: true, children: 8, kind: "folder", mime: "inode/directory" },
  { ...file("voice/outputs", 0, "folder"), is_dir: true, children: 23, kind: "folder", mime: "inode/directory" },
  { ...file("images/album-art", 0, "folder"), is_dir: true, children: 31, kind: "folder", mime: "inode/directory" },
  { ...file("subtitles/67c9de20/nocturno.srt", 3120, "subtitle") },
  { ...file("music/nocturno/master/nocturno-master.wav", 52_428_288, "audio") },
  { ...file("video/atravessar-noite/output/final_video.mp4", 184_549_376, "video") },
  { ...file("documents/33af9e88/audio.mp3", 16_200_432, "audio") },
  { ...file("images/album-art/cover-porcelain-city.png", 2_884_301, "image") },
  { ...file("uploads/lyrics-nocturno.txt", 4210, "document") },
];

export const demoImagePaths = Array.from({ length: 8 }, (_, index) => `/demo/art-${String(index + 1).padStart(2, "0")}.png`);

export const demoGallery = demoImagePaths.map((path, index) => ({
  path: `images/gallery/art-${String(index + 1).padStart(2, "0")}.png`,
  url: path,
  prompt: [
    "Porcelain city at dusk, cinematic, violet haze",
    "A lone figure crossing a flooded avenue, neon reflections",
    "Analog synthesizer cathedral, warm dust and light",
    "Ocean cliff at blue hour, long exposure",
    "Botanical instrument, macro photography",
    "Brutalist listening room, amber light",
    "Night train window, motion blur, teal",
    "Desert radio tower, pink sky, grain",
  ][index],
  provider: index % 3 === 0 ? "diffusers" : index % 3 === 1 ? "procedural" : "comfyui",
  width: 1024,
  height: 1024,
  seed: 1000 + index * 37,
  created_at: iso(20 + index * 45),
}));

export const demoProjects = [
  {
    id: "nocturno",
    title: "Nocturno",
    artist: "Helena Rocha",
    description: "A nocturnal art-pop record about crossing a city after midnight.",
    color: "#8b5cf6",
    song_count: 4,
    take_count: 11,
    updated_at: iso(12),
  },
  {
    id: "atravessar-noite",
    title: "Atravessar a Noite",
    artist: "Helena Rocha",
    description: "Portuguese-language companion EP, recorded live in one room.",
    color: "#22d3ee",
    song_count: 3,
    take_count: 7,
    updated_at: iso(80),
  },
  {
    id: "field-notes",
    title: "Field Notes",
    artist: "Open Studio",
    description: "Instrumental sketches built from field recordings and tape loops.",
    color: "#f59e0b",
    song_count: 6,
    take_count: 18,
    updated_at: iso(600),
  },
];

export const demoSongs = [
  { id: "s1", project_id: "nocturno", title: "Nocturno", genre: "Art pop", mood: "Introspective", bpm: 78, duration: 214, language: "pt-PT", take_count: 5, updated_at: iso(12) },
  { id: "s2", project_id: "nocturno", title: "Glass Avenue", genre: "Dream pop", mood: "Yearning", bpm: 92, duration: 198, language: "en", take_count: 3, updated_at: iso(90) },
  { id: "s3", project_id: "nocturno", title: "Static Bloom", genre: "Electronic", mood: "Haunting", bpm: 104, duration: 176, language: "en", take_count: 2, updated_at: iso(200) },
  { id: "s4", project_id: "nocturno", title: "Last Light", genre: "Art pop", mood: "Serene", bpm: 68, duration: 240, language: "pt-PT", take_count: 1, updated_at: iso(400) },
];

export const demoLyrics = {
  sections: [
    { id: "l1", type: "verse", label: "Verse 1", content: "A cidade fecha os olhos devagar\nEu conto os passos até te encontrar\nHá luz nas janelas que ninguém apagou\nE um fio de voz que nunca se calou", instructions: "Intimate, close to the microphone" },
    { id: "l2", type: "chorus", label: "Chorus", content: "Nocturno, nocturno\nDança comigo no escuro\nNocturno, nocturno\nAté o silêncio ficar maduro", instructions: "Open, soaring harmony" },
    { id: "l3", type: "verse", label: "Verse 2", content: "As ruas são rios que sabem voltar\nCada esquina é um lugar para ficar\nSe o mundo dormir, eu fico acordado\nGuardando o teu nome do lado errado", instructions: "Lower register, restrained" },
    { id: "l4", type: "outro", label: "Outro", content: "Nocturno...\nNão acordes ainda", instructions: "Fade with breath" },
  ],
};

export const demoTakes = [
  { id: "t1", position: 1, path: "music/nocturno/master/nocturno-master.wav", seed: 438921, duration: 214.4, bpm: 78, favorite: true, selected: true, created_at: iso(24), metadata: { mode: "full", model: "acestep-v15-turbo" } },
  { id: "t2", position: 2, path: "music/nocturno/takes/nocturno-v2.wav", seed: 438922, duration: 211.8, bpm: 78, favorite: false, selected: false, created_at: iso(95), metadata: { mode: "full", model: "acestep-v15-turbo" } },
  { id: "t3", position: 3, path: "music/nocturno/takes/nocturno-cover.wav", seed: 91210, duration: 208.2, bpm: 78, favorite: false, selected: false, created_at: iso(300), metadata: { mode: "cover", model: "acestep-v15-sft" } },
];

export const demoMusicCatalog = {
  engines: [
    { id: "ace_step", name: "ACE-Step 1.5 C++", available: true, status: "ready", device: "CPU · OpenBLAS", detail: "GGUF engine" },
    { id: "preview", name: "Procedural preview", available: true, status: "ready", device: "CPU", detail: "No model weights" },
  ],
  models: [
    { id: "acestep-v15-turbo", name: "ACE-Step 1.5 Turbo", short_name: "Turbo 2B", parameters: "2B", speed: "fast", quality: "high", installed: true, default: true, capabilities: ["text_to_music", "lyrics", "vocals", "instrumental", "cover", "repaint", "reference_audio"] },
    { id: "acestep-v15-sft", name: "ACE-Step 1.5 SFT", short_name: "SFT 2B", parameters: "2B", speed: "slow", quality: "highest", installed: true, capabilities: ["text_to_music", "lyrics", "cover", "repaint", "extend"] },
    { id: "acestep-v15-base", name: "ACE-Step 1.5 Base", short_name: "Base 2B", parameters: "2B", speed: "slow", quality: "studio", installed: false, capabilities: ["text_to_music", "extend", "repaint"] },
  ],
  languages: [
    { code: "pt-PT", label: "Portuguese (Portugal)" },
    { code: "pt-BR", label: "Portuguese (Brazil)" },
    { code: "en", label: "English" },
    { code: "es", label: "Spanish" },
    { code: "fr", label: "French" },
    { code: "de", label: "German" },
    { code: "it", label: "Italian" },
    { code: "ja", label: "Japanese" },
  ],
  options: {
    genres: ["Art pop", "Dream pop", "Electronic", "Trip hop", "Folk", "Jazz", "Ambient", "Rock"],
    moods: ["Introspective", "Yearning", "Haunting", "Serene", "Defiant", "Joyful", "Mournful", "Ecstatic"],
    vocal_types: ["female", "male", "duet", "group", "choir", "instrumental"],
    singing_styles: ["Melodic", "Intimate", "Breathy", "Belting", "Falsetto", "Spoken word", "Rap", "Chant"],
  },
  defaults: { mode: "full", variations: 2, duration: 180, bpm: 90, steps: 8, guidance: 7, infer_method: "ode" },
};

export const demoVideoCatalog = {
  styles: [
    { id: "cinematic", name: "Cinematic", description: "Anamorphic light, deep shadows and slow camera moves.", palette: ["#08111F", "#F4A261", "#E9C46A"] },
    { id: "noir", name: "Noir", description: "High contrast monochrome, rain and hard key light.", palette: ["#050506", "#D7D7D7", "#8A8A8A"] },
    { id: "synthwave", name: "Synthwave", description: "Neon gradients, chrome and retro sunsets.", palette: ["#1A0B2E", "#FF2E97", "#00E5FF"] },
    { id: "watercolor", name: "Watercolor", description: "Soft paper texture and bleeding pigment.", palette: ["#F7F3EA", "#87A7B3", "#D19C97"] },
    { id: "anime", name: "Anime", description: "Clean lines, dramatic skies and luminous color.", palette: ["#0B1D3A", "#5BC0EB", "#FDE74C"] },
    { id: "documentary", name: "Documentary", description: "Natural light, handheld texture, honest framing.", palette: ["#2B2B28", "#C7B9A5", "#6B705C"] },
  ],
  animation_backends: ["ffmpeg", "opencv", "ai"],
  image_providers: ["auto", "procedural", "diffusers", "comfyui", "qvac"],
  resolutions: ["1280x720", "1920x1080", "3840x2160", "1080x1920", "1080x1080"],
  codecs: ["h264", "h265"],
  camera_moves: ["slow_push", "pull_back", "pan_left", "pan_right", "tilt_up", "tilt_down", "orbit", "handheld", "static"],
  transitions: ["cut", "fade", "dissolve", "wipe_left", "wipe_up", "zoom_blur"],
  effects: ["film_grain", "vignette", "bloom", "chromatic_aberration", "light_leak", "particles", "beat_pulse", "bass_pulse"],
  defaults: { width: 1920, height: 1080, fps: 30, codec: "h264", animation_backend: "ffmpeg", image_provider: "auto", scene_seconds: 8 },
};

export const demoVideoProject = {
  id: "atravessar-noite",
  name: "atravessar-noite",
  title: "Atravessar a Noite",
  artist: "Helena Rocha",
  stage: "rendered",
  duration: 214.6,
  scene_count: 18,
  updated_at: iso(6),
  final_video: "video/projects/atravessar-noite/output/final_video.mp4",
  final_thumbnail: "video/projects/atravessar-noite/output/thumbnail.jpg",
  config: {
    style_id: "cinematic",
    visual_style_prompt: "Portuguese city at night, wet asphalt, sodium and teal light, 35mm anamorphic",
    width: 1920,
    height: 1080,
    fps: 30,
    codec: "h264",
    animation_backend: "ffmpeg",
    image_provider: "auto",
    scene_target_seconds: 8,
    subtitle_style: "karaoke",
    audio_reactive: { enabled: true, beat_pulse: true, bass_pulse: true, beat_cuts: true, particles: false, intensity: 0.55 },
  },
};

export const demoScenes = [
  { id: 1, start: 0, end: 11.4, kind: "intro", description: "Empty avenue, rain on asphalt, neon signs out of focus.", camera: "slow_push", transition: "fade", visual_effects: ["film_grain", "bloom"], image_path: "/demo/art-02.png", video_path: "video/projects/atravessar-noite/assets/videos/scene_001.mp4", status: "animated" },
  { id: 2, start: 11.4, end: 24.2, kind: "verse", description: "A lone figure under a street light, breath visible.", camera: "pan_left", transition: "dissolve", visual_effects: ["vignette", "particles"], image_path: "/demo/art-07.png", video_path: "video/projects/atravessar-noite/assets/videos/scene_002.mp4", status: "animated" },
  { id: 3, start: 24.2, end: 38.8, kind: "chorus", description: "The city opens up, traffic streaks and reflections bloom.", camera: "orbit", transition: "zoom_blur", visual_effects: ["bloom", "beat_pulse"], image_path: "/demo/art-01.png", video_path: "video/projects/atravessar-noite/assets/videos/scene_003.mp4", status: "animated" },
  { id: 4, start: 38.8, end: 51.1, kind: "verse", description: "Close-up of hands on a rain-soaked railing.", camera: "tilt_up", transition: "cut", visual_effects: ["film_grain"], image_path: "/demo/art-04.png", video_path: "video/projects/atravessar-noite/assets/videos/scene_004.mp4", status: "animated" },
  { id: 5, start: 51.1, end: 64.0, kind: "chorus", description: "A wide bridge, the river carrying the city lights away.", camera: "pull_back", transition: "dissolve", visual_effects: ["bloom", "light_leak"], image_path: "/demo/art-05.png", video_path: "video/projects/atravessar-noite/assets/videos/scene_005.mp4", status: "animated" },
  { id: 6, start: 64.0, end: 78.6, kind: "bridge", description: "Empty apartment, curtains moving, television static.", camera: "handheld", transition: "fade", visual_effects: ["grain", "chromatic_aberration"], image_path: "/demo/art-06.png", video_path: "video/projects/atravessar-noite/assets/videos/scene_006.mp4", status: "animated" },
];

export const demoVoiceCatalog = {
  engines: [
    { id: "omnivoice", name: "OmniVoice", status: "ready", device: "CUDA · RTX 4090", detail: "Zero-shot cloning · 646 languages" },
    { id: "piper", name: "Piper", status: "ready", device: "CPU", detail: "5 fast built-in voices" },
  ],
  modes: ["auto", "voice", "design"],
  formats: ["wav", "mp3", "flac"],
  languages: [
    { id: "pt-PT", name: "Portuguese (Portugal)" },
    { id: "pt-BR", name: "Portuguese (Brazil)" },
    { id: "en", name: "English" },
    { id: "es", name: "Spanish" },
    { id: "fr", name: "French" },
    { id: "de", name: "German" },
    { id: "it", name: "Italian" },
    { id: "ja", name: "Japanese" },
    { id: "zh", name: "Chinese" },
  ],
  limits: { max_input_chars: 8000, max_voice_seconds: 30, batch_items: 50 },
  advanced: { num_step: 32, guidance_scale: 2.0, t_shift: 0.5, denoise: true, speed: 1.0 },
};

export const demoVoices = [
  { id: "v1", name: "Helena — close", language: "pt-PT", duration_seconds: 8.4, transcript: "Há dias em que a cidade parece feita de vidro.", has_preview: true, created_at: iso(60 * 24 * 3), preview: "/demo/voice-preview.wav" },
  { id: "v2", name: "Narrator — warm", language: "en", duration_seconds: 12.1, transcript: "This is a story about the hours between midnight and dawn.", has_preview: true, created_at: iso(60 * 24 * 8), preview: null },
  { id: "v3", name: "Rui — low", language: "pt-PT", duration_seconds: 6.8, transcript: "O rio lembra-se de tudo o que lhe contamos.", has_preview: true, created_at: iso(60 * 24 * 12), preview: null },
];

export const demoVoiceOutputs = [
  { id: "o1", text: "A cidade fecha os olhos devagar. Eu conto os passos até te encontrar.", voice_name: "Helena — close", language: "pt-PT", duration_seconds: 8.9, format: "mp3", created_at: iso(20), path: "voice/outputs/2c7e1a55/chapter-03.mp3" },
  { id: "o2", text: "Nocturno, nocturno. Dança comigo no escuro.", voice_name: "Helena — close", language: "pt-PT", duration_seconds: 4.2, format: "wav", created_at: iso(70), path: "voice/outputs/o2/line.wav" },
  { id: "o3", text: "Chapter three. The train arrived at the coast just before sunrise.", voice_name: "Narrator — warm", language: "en", duration_seconds: 6.1, format: "mp3", created_at: iso(140), path: "voice/outputs/o3/chapter.mp3" },
];

export const demoPiperVoices = [
  { id: "pt-PT-tugao", name: "Tugão", language: "pt-PT", gender: "male", available: true },
  { id: "pt-PT-dii", name: "Dii", language: "pt-PT", gender: "female", available: true },
  { id: "pt-BR-faber", name: "Faber", language: "pt-BR", gender: "male", available: true },
  { id: "pt-BR-dii", name: "Dii", language: "pt-BR", gender: "female", available: false },
  { id: "en-US-lessac", name: "Lessac", language: "en-US", gender: "female", available: true },
];

export const demoCues = [
  { index: 1, start: 0.42, end: 4.8, text: "A cidade fecha os olhos devagar" },
  { index: 2, start: 4.8, end: 9.1, text: "Eu conto os passos até te encontrar" },
  { index: 3, start: 9.1, end: 13.6, text: "Há luz nas janelas que ninguém apagou" },
  { index: 4, start: 13.6, end: 18.2, text: "E um fio de voz que nunca se calou" },
  { index: 5, start: 19.0, end: 22.4, text: "Nocturno, nocturno" },
  { index: 6, start: 22.4, end: 26.8, text: "Dança comigo no escuro" },
  { index: 7, start: 26.8, end: 30.1, text: "Nocturno, nocturno" },
  { index: 8, start: 30.1, end: 34.6, text: "Até o silêncio ficar maduro" },
];

export const demoSubtitlesCatalog = {
  models: ["tiny", "base", "small", "medium", "large-v3", "distil-large-v3"],
  languages: ["auto", "pt", "en", "es", "fr", "de", "it", "ja"],
  defaults: { model: "large-v3", language: "pt", beam_size: 5, vad_filter: true, word_timestamps: true },
};

export const demoTranslateLanguages = {
  source: ["auto", "pt", "pt-PT", "pt-BR", "en", "es", "fr", "de", "it", "ja", "zh"],
  target: ["en", "pt-PT", "pt-BR", "es", "fr", "de", "it", "ja", "zh"],
  pairs: [{ source: "pt", target: "en" }, { source: "en", target: "pt-PT" }, { source: "en", target: "pt-BR" }],
};

export const demoTranslation = {
  source_language: "pt",
  target_language: "en",
  translated_text:
    "The city closes its eyes slowly\nI count the steps until I find you\nThere is light in the windows that no one turned off\nAnd a thread of voice that never fell silent\n\nNocturne, nocturne\nDance with me in the dark\nNocturne, nocturne\nUntil the silence ripens",
  stats: { input_characters: 214, output_characters: 206, paragraphs: 2, chunks: 2, device: "cpu" },
  duration_seconds: 1.4,
  model: "Helsinki-NLP/opus-mt-roa-en",
};

export const demoSummary = {
  summary:
    "The report describes a year of steady growth in local-first creative tooling. Revenue rose 24%, driven by studio subscriptions and enterprise deployments. The team shipped four new model integrations, cut inference latency by 38%, and reduced storage costs through content-addressed assets. Priorities for next year are video generation, multilingual voice, and a unified job system that lets every service run in parallel.",
  source_language: "en",
  language: "en",
  length: "medium",
  input_words: 2480,
  output_words: 68,
  chunk_count: 5,
  duration_seconds: 2.8,
  model: "t5-small",
  warnings: [],
};

export const demoDocsCapabilities = {
  inputs: ["pdf", "text"],
  translation_languages: demoTranslateLanguages,
  summary_lengths: ["short", "medium", "long"],
  tts_engines: ["omnivoice", "piper"],
  voices: demoVoices,
  piper_voices: demoPiperVoices,
  formats: ["mp3", "wav", "flac"],
  limits: { max_pages: 2000, max_text_chars: 500000, max_upload_mb: 200 },
};

export const demoDocResult = {
  job_id: "33af9e88",
  title: "Relatório anual 2026",
  source: "annual-report-2026.pdf",
  pages: 42,
  extracted:
    "--- Page 1 ---\n\nAnnual Report 2026\nOpen Studio GmbH\n\n--- Page 2 ---\n\nThe past year was defined by a shift from isolated creative tools to integrated local workflows. Customers asked for one place where music, video, voice and documents could share the same files, the same jobs and the same privacy model.",
  translation:
    "--- Page 1 ---\n\nRelatório Anual 2026\nOpen Studio GmbH\n\n--- Page 2 ---\n\nO ano passado foi definido por uma mudança de ferramentas criativas isoladas para fluxos de trabalho locais integrados.",
  summary:
    "Open Studio grew 24% in 2026 as customers consolidated music, video, voice and document workflows into a single local-first workspace. The team shipped four model integrations, reduced inference latency by 38% and introduced a shared file system and global job queues.",
  audio_path: "documents/33af9e88/audio.mp3",
  srt_path: "documents/33af9e88/subtitles.srt",
  vtt_path: "documents/33af9e88/captions.vtt",
  zip_path: "documents/33af9e88/output.zip",
};

export const demoFFmpegCatalog = {
  version: "7.0.2",
  operations: [
    "transcode", "extract_audio", "trim", "crop_video", "crop_image", "scale", "rotate", "concat", "overlay", "subtitles", "frames", "gif", "merge", "replace_audio", "speed", "volume", "normalize", "thumbnail", "split", "raw",
  ],
  video_codecs: ["libx264", "libx265", "libvpx-vp9", "prores_ks"],
  audio_codecs: ["aac", "libmp3lame", "libopus", "flac", "pcm_s16le"],
  formats: ["mp4", "mkv", "mov", "webm", "mp3", "wav", "flac", "aac", "opus", "gif", "png", "jpg"],
  filters: ["scale", "crop", "fade", "xfade", "subtitles", "overlay", "loudnorm", "dynaudnorm", "eq", "hue", "unsharp", "vignette", "colorbalance", "noise"],
};

export const demoProbe = {
  duration: 214.6,
  size: 184549376,
  bit_rate: 6879000,
  format_name: "mov,mp4,m4a,3gp,3g2,mj2",
  format_long_name: "QuickTime / MOV",
  streams: [
    { index: 0, type: "video", codec: "h264", width: 1920, height: 1080, fps: 30, bit_rate: 6420000, pix_fmt: "yuv420p", language: "und" },
    { index: 1, type: "audio", codec: "aac", sample_rate: 48000, channels: 2, bit_rate: 317000, language: "por" },
  ],
};

export const demoYtInfo = {
  id: "dQw4w9WgXcQ",
  title: "Field Recording — Lisbon at 4am (binaural)",
  uploader: "Open Studio Field Notes",
  duration: 1842,
  duration_string: "30:42",
  view_count: 182034,
  upload_date: "2026-09-18",
  webpage_url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  thumbnail: "/demo/art-08.png",
  description: "Binaural field recording made between 4am and sunrise around Lisbon. Headphones recommended.",
  formats: [
    { format_id: "137", ext: "mp4", resolution: "1920x1080", fps: 30, vcodec: "avc1.640028", acodec: "none", filesize: 184000000, tbr: 6420 },
    { format_id: "248", ext: "webm", resolution: "1920x1080", fps: 30, vcodec: "vp9", acodec: "none", filesize: 162000000, tbr: 5800 },
    { format_id: "140", ext: "m4a", resolution: "audio only", fps: null, vcodec: "none", acodec: "mp4a.40.2", filesize: 29400000, tbr: 129 },
    { format_id: "251", ext: "webm", resolution: "audio only", fps: null, vcodec: "none", acodec: "opus", filesize: 28100000, tbr: 124 },
  ],
};

export const demoQvacCatalog = {
  version: "0.23.0",
  device: "gpu",
  memory: { total_gb: 24, free_gb: 21.4, unified: false },
  modes: ["txt2vid", "img2vid"],
  families: [
    { id: "wan21-t2v", name: "WAN 2.1 T2V 1.3B", params: "1.3B", vram: "8 GB", mode: "txt2vid", installed: true },
    { id: "wan21-i2v", name: "WAN 2.1 I2V 14B", params: "14B", vram: "16 GB", mode: "img2vid", installed: false },
    { id: "wan22-ti2v", name: "Wan 2.2 TI2V-5B", params: "5B", vram: "16 GB", mode: "txt2vid", installed: true },
    { id: "ltx2", name: "LTX-2 22B", params: "22B", vram: "20 GB", mode: "txt2vid + audio", installed: false },
    { id: "minimax-h3", name: "MiniMax-H3", params: "H3", vram: "16 GB", mode: "txt2vid + audio", installed: false },
  ],
  constraints: { width_multiple: 16, wan_frames: "4k + 1", ltx_frames: "8k + 1", h3_frames: "17k + 5" },
  defaults: { width: 480, height: 832, video_frames: 33, fps: 16, steps: 30, cfg_scale: 6, flow_shift: 3, seed: 42 },
};

export const demoQvacStatus = {
  status: "ready",
  sdk: "0.23.0",
  device: "gpu",
  backend: "Vulkan · stable-diffusion.cpp",
  loaded: { model_id: "wan21-t2v", name: "WAN 2.1 T2V 1.3B", mode: "video" },
  memory: { total_gb: 24, used_gb: 9.8 },
  queue: { running: 0, queued: 0 },
};

export const demoServices = {
  items: [
    { name: "files", label: "Files", description: "Shared storage API", group: "Core", core: true, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/files", container: "openstudio-files", status: "Up" },
    { name: "jobhub", label: "Job Hub", description: "Global queues", group: "Core", core: true, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/jobhub", container: "openstudio-jobhub", status: "Up" },
    { name: "admin", label: "Service Manager", description: "On-demand builds and health", group: "Core", core: true, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/admin", container: "openstudio-admin", status: "Up" },
    { name: "gateway", label: "Gateway", description: "Auth and API proxy", group: "Core", core: true, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/gateway", container: "openstudio-gateway", status: "Up" },
    { name: "frontend", label: "Frontend", description: "Vue app", group: "Core", core: true, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/frontend", container: "openstudio-frontend", status: "Up" },
    { name: "chat", label: "Chat", description: "Persistent local ChatGPT-style conversations", group: "Core AI", core: true, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: ["llm"], image: "openstudio/chat", container: "openstudio-chat", status: "Up" },
    { name: "music", label: "Music Studio", description: "ACE-Step songs, lyrics and takes", group: "Create", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: ["music-engine"], image: "openstudio/music", container: "openstudio-music", status: "Up" },
    { name: "music-engine", label: "ACE-Step Engine", description: "GGUF/C++ music inference", group: "Engines", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/music-engine", container: "openstudio-music-engine", status: "Up" },
    { name: "dj", label: "DJ Studio", description: "Analysis, style models, AI arrangements and mix scenes", group: "Create", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/dj", container: "openstudio-dj", status: "Up" },
    { name: "video", label: "Video Studio", description: "Full video pipeline", group: "Create", core: false, enabled: false, running: false, state: "absent", health: "disabled", image_built: true, requires: ["video-audio", "video-lyrics", "video-planner", "video-animation", "video-renderer", "imagegen"], image: "openstudio/video", container: "", status: "disabled" },
    { name: "voice", label: "Voice / TTS", description: "OmniVoice + Piper", group: "Create", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/voice", container: "openstudio-voice", status: "Up" },
    { name: "srt", label: "AI Subtitles", description: "Whisper + lyric alignment", group: "Create", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/srt", container: "openstudio-srt", status: "Up" },
    { name: "imagegen", label: "Picture Studio", description: "Diffusers / ComfyUI / QVAC images", group: "Create", core: false, enabled: false, running: false, state: "absent", health: "disabled", image_built: true, requires: [], image: "openstudio/imagegen", container: "", status: "disabled" },
    { name: "docs", label: "Documents", description: "PDF → translation → speech", group: "Text", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: ["pdf", "translation", "summary", "voice", "ffmpeg"], image: "openstudio/docs", container: "openstudio-docs", status: "Up" },
    { name: "translation", label: "Translation", description: "OPUS-MT / NLLB", group: "Text", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/translation", container: "openstudio-translation", status: "Up" },
    { name: "summary", label: "Summaries", description: "Hierarchical T5", group: "Text", core: false, enabled: false, running: false, state: "absent", health: "disabled", image_built: true, requires: [], image: "openstudio/summary", container: "", status: "disabled" },
    { name: "pdf", label: "PDF / OCR", description: "PyMuPDF + Tesseract", group: "Text", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/pdf", container: "openstudio-pdf", status: "Up" },
    { name: "ffmpeg", label: "FFmpeg", description: "Media workbench", group: "Tools", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/ffmpeg", container: "openstudio-ffmpeg", status: "Up" },
    { name: "ytdlp", label: "yt-dlp", description: "Media downloader", group: "Tools", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: [], image: "openstudio/ytdlp", container: "openstudio-ytdlp", status: "Up" },
    { name: "qvac", label: "QVAC", description: "Local video diffusion", group: "Create", core: false, enabled: false, running: false, state: "absent", health: "disabled", image_built: true, requires: [], image: "openstudio/qvac", container: "", status: "disabled" },
    { name: "llm", label: "LLM Bridge", description: "OpenAI-compatible bridge", group: "Core AI", core: false, enabled: true, running: true, state: "running", health: "healthy", image_built: true, requires: ["ollama"], image: "openstudio/llm", container: "openstudio-llm", status: "Up" },
    { name: "ollama", label: "Ollama", description: "Local LLM runtime", group: "Core AI", core: false, enabled: false, running: false, state: "absent", health: "disabled", image_built: true, requires: [], image: "ollama/ollama", container: "", status: "disabled" },
  ],
  enabled: 15,
  running: 15,
  total: 22,
};

export const demoSystemInfo = {
  version: "1.0.0",
  files_root: "/data/files",
  features: { auth: true, jobs: true, shared_files: true, gpu: true },
  services: demoStatus.services.map((service) => ({ name: service.name, label: service.label, category: service.category, prefix: `/api/${service.name}` })),
};

export const demoAuthStatus = {
  setup_required: false,
  authenticated: true,
  password_set_at: iso(60 * 24 * 30),
  identity: { type: "session", id: "demo_session" },
  version: "1.0.0",
};
