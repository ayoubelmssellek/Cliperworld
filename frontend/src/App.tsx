import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type SubmitEvent,
} from 'react'
import './App.css'

type Tools = Record<string, boolean>

type Clip = {
  id: string
  start: number
  end: number
  peak_second: number
  score: number
  sample_messages: string[]
  video_path?: string | null
  captioned_path?: string | null
  status: string
  title?: string | null
  description?: string | null
  hashtags?: string[]
  hook?: string | null
  reason?: string | null
  source?: string
}

type VodInfo = {
  title?: string
  streamer?: string
  category?: string
  length_label?: string
  views?: number
  thumbnail?: string | null
}

type Job = {
  id: string
  url: string
  status: string
  message: string
  error?: string | null
  clips: Clip[]
  spikes?: { peak_second: number; score: number; message_count: number }[]
  vod_id?: string | null
  platform?: string
  video_path?: string | null
  chat_path?: string | null
  with_gemma?: boolean
  with_captions?: boolean
  quality?: string
  layout?: string
  cam_zoom?: number
  game_zoom?: number
  game_pan?: number
  updated_at?: number
  created_at?: number
  meta?: {
    stage?: string
    progress?: number
    activity?: string
    spike_count?: number
    caption_error?: string
    gemma_error?: string
    gemma_hint?: string
    gemma_picks?: number
    chat_download_error?: string
    picker?: string
    kitty_model?: string
    format?: string
    layout?: string
    cam_zoom?: number
    game_zoom?: number
    game_pan?: number
    caption_style?: Partial<CaptionStyle>
    vod?: VodInfo
    download?: {
      bytes_label?: string
      phase?: string
      line?: string
    }
    clip_progress?: {
      index?: number
      total?: number
      done?: number
      phase?: string
      label?: string
    }
  }
}

type Health = {
  ok: boolean
  app: string
  tools: Tools
}

type CaptionStyle = {
  alignment: 'top' | 'middle' | 'bottom'
  font_name: string
  font_size: number
  font_color: string
  highlight_color: string
  margin_v: number
  uppercase: boolean
  effect: string
}

type NavSection = 'studio' | 'jobs' | 'engines' | 'settings'

const API = import.meta.env.VITE_API_URL ?? ''
const SETTINGS_KEY = 'cliperworld.settings.v1'

const QUALITY_OPTIONS = [
  { value: '360', label: '360p · fast' },
  { value: '480', label: '480p' },
  { value: '720', label: '720p · cam layouts' },
  { value: '1080', label: '1080p' },
  { value: 'best', label: 'Best' },
] as const

const LAYOUT_OPTIONS = [
  {
    value: 'blur',
    label: 'Blur fill',
    blurb: 'Centered gameplay · soft backdrop',
  },
  {
    value: 'full_hook',
    label: 'Full plate · Hook',
    blurb: 'Full 16:9 · explain text on top',
  },
  {
    value: 'cam_hook_game',
    label: 'Cam · Hook · Game',
    blurb: 'Facecam top · title bar · gameplay',
  },
  {
    value: 'game_hook_cam',
    label: 'Game · Hook · Cam',
    blurb: 'Gameplay top · title bar · facecam',
  },
  {
    value: 'face',
    label: 'Face track',
    blurb: 'Follow the speaker in 9:16',
  },
] as const

const NAV_ITEMS: { id: NavSection; label: string; hint: string }[] = [
  { id: 'studio', label: 'Studio', hint: 'Create Shorts' },
  { id: 'jobs', label: 'Jobs', hint: 'History' },
  { id: 'engines', label: 'Engines', hint: 'Tool health' },
  { id: 'settings', label: 'Settings', hint: 'Defaults' },
]

const STAGES = [
  { id: 'info', label: 'Cover' },
  { id: 'downloading_video', label: 'Video' },
  { id: 'downloading_chat', label: 'Chat' },
  { id: 'analyzing_chat', label: 'Spikes' },
  { id: 'gemma', label: 'Gemma' },
  { id: 'cutting', label: 'Cut' },
  { id: 'shorts', label: '9:16' },
  { id: 'captioning', label: 'Caps' },
  { id: 'done', label: 'Done' },
] as const

const CORE_ENGINE_KEYS = [
  'ffmpeg',
  'twitch_downloader',
  'yt_dlp',
  'clips_studio',
  'ollama',
  'gemma',
  'openshorts',
  'vertify',
  'whisperx',
  'streamcut_facecam',
]

const CAPTION_FONTS = [
  { value: 'Anton', label: 'Anton · bold Shorts' },
  { value: 'Montserrat ExtraBold', label: 'Montserrat · clean' },
  { value: 'Impact', label: 'Impact · condensed' },
] as const

const CAPTION_PRESETS = [
  {
    id: 'default',
    label: 'Classic',
    style: {
      alignment: 'bottom',
      font_name: 'Anton',
      font_size: 40,
      font_color: '#FFFFFF',
      highlight_color: '#FFE500',
      margin_v: 43,
      uppercase: true,
      effect: 'pop',
    },
  },
  {
    id: 'hormozi',
    label: 'Hormozi',
    style: {
      alignment: 'bottom',
      font_name: 'Montserrat ExtraBold',
      font_size: 44,
      font_color: '#FFFFFF',
      highlight_color: '#FFE500',
      margin_v: 36,
      uppercase: true,
      effect: 'pop',
    },
  },
  {
    id: 'lime',
    label: 'Lime',
    style: {
      alignment: 'middle',
      font_name: 'Montserrat ExtraBold',
      font_size: 44,
      font_color: '#FFFFFF',
      highlight_color: '#A3FF12',
      margin_v: 28,
      uppercase: true,
      effect: 'highlight',
    },
  },
  {
    id: 'cine',
    label: 'Cine',
    style: {
      alignment: 'bottom',
      font_name: 'Montserrat ExtraBold',
      font_size: 36,
      font_color: '#FFFFFF',
      highlight_color: '#FF5A1F',
      margin_v: 48,
      uppercase: false,
      effect: 'none',
    },
  },
] as const

const DEFAULT_CAPTION_STYLE: CaptionStyle = {
  alignment: 'bottom',
  font_name: 'Anton',
  font_size: 40,
  font_color: '#FFFFFF',
  highlight_color: '#FFE500',
  margin_v: 43,
  uppercase: true,
  effect: 'pop',
}

type Prefs = {
  layout: (typeof LAYOUT_OPTIONS)[number]['value']
  quality: string
  withCaptions: boolean
  withGemma: boolean
}

function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    if (!raw) {
      return {
        layout: 'cam_hook_game',
        quality: '720',
        withCaptions: true,
        withGemma: true,
      }
    }
    const parsed = JSON.parse(raw) as Partial<Prefs>
    const layoutValues = LAYOUT_OPTIONS.map((o) => o.value)
    return {
      layout: layoutValues.includes(parsed.layout as Prefs['layout'])
        ? (parsed.layout as Prefs['layout'])
        : 'cam_hook_game',
      quality: parsed.quality || '720',
      withCaptions: parsed.withCaptions !== false,
      withGemma: parsed.withGemma !== false,
    }
  } catch {
    return {
      layout: 'cam_hook_game',
      quality: '720',
      withCaptions: true,
      withGemma: true,
    }
  }
}

function savePrefs(prefs: Prefs) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(prefs))
}

function formatTime(seconds: number) {
  const s = Math.max(0, Math.floor(seconds))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${r.toString().padStart(2, '0')}`
}

function stageIndex(stage?: string) {
  if (!stage) return 0
  if (stage === 'failed' || stage === 'cancelled') return -1
  if (stage === 'downloading') return 1
  const idx = STAGES.findIndex((s) => s.id === stage)
  return idx >= 0 ? idx : 0
}

type StepState = 'todo' | 'current' | 'done' | 'fail' | 'skip'

function stepStates(job: Job): StepState[] {
  const stage = job.meta?.stage || job.status
  const idx = stageIndex(stage)
  const failed = job.status === 'failed' || job.status === 'cancelled'
  const allDone = job.status === 'done'
  const gemmaSkipped = job.with_gemma === false
  const capsSkipped = job.with_captions === false

  const doneFlags = [
    Boolean(job.meta?.vod?.title || job.meta?.vod?.streamer || job.vod_id) || idx > 0,
    Boolean(job.video_path) || idx > 1,
    Boolean(job.chat_path) || Boolean(job.meta?.chat_download_error) || idx > 2,
    (job.spikes?.length || 0) > 0 || Number(job.meta?.spike_count || 0) > 0 || idx > 3,
    typeof job.meta?.gemma_picks === 'number' ||
      Boolean(job.meta?.gemma_error) ||
      job.meta?.picker === 'gemma+chat' ||
      idx > 4,
    (job.clips || []).some((c) =>
      ['cut', 'short', 'captioned', 'ready'].includes(c.status),
    ) || idx > 5,
    (job.clips || []).some((c) =>
      ['short', 'captioned', 'ready'].includes(c.status),
    ) || idx > 6,
    (job.clips || []).some((c) => Boolean(c.captioned_path) || c.status === 'captioned') ||
      Boolean(job.meta?.caption_error) ||
      idx > 7,
    allDone,
  ]

  return STAGES.map((_, i) => {
    if ((i === 4 && gemmaSkipped) || (i === 7 && capsSkipped)) return 'skip'
    if (failed && i <= Math.max(idx, 0)) return 'fail'
    if (allDone) return 'done'
    if (i === idx) return 'current'
    if (i < idx || doneFlags[i]) return 'done'
    return 'todo'
  })
}

function isTerminal(status?: string) {
  return status === 'done' || status === 'failed' || status === 'cancelled'
}

function statusHeadline(job: Job) {
  const stage = job.meta?.stage || job.status
  const labels: Record<string, string> = {
    info: 'cover',
    downloading_video: 'downloading video',
    downloading_chat: 'downloading chat',
    downloading: 'downloading',
    analyzing_chat: 'spikes',
    gemma: 'gemma',
    cutting: 'cutting',
    shorts: '9:16',
    captioning: 'captions',
    done: 'done',
    failed: 'failed',
    cancelled: 'cancelled',
  }
  return labels[stage] || job.status.replaceAll('_', ' ')
}

function toolLabel(name: string) {
  return name.replaceAll('_', ' ')
}

function clipMediaUrl(
  jobId: string,
  filePath?: string | null,
  cacheKey?: number | string | null,
) {
  if (!filePath) return null
  const name = filePath.replace(/\\/g, '/').split('/').pop()
  if (!name) return null
  const bust = cacheKey != null ? `?v=${cacheKey}` : ''
  return `${API}/media/clips/${jobId}/${name}${bust}`
}

function jobTitle(job: Job) {
  return (
    job.meta?.vod?.title ||
    job.meta?.vod?.streamer ||
    (job.vod_id ? `VOD ${job.vod_id}` : job.url.slice(0, 48))
  )
}

export default function App() {
  const initialPrefs = useMemo(() => loadPrefs(), [])
  const [section, setSection] = useState<NavSection>('studio')
  const [url, setUrl] = useState('')
  const [withCaptions, setWithCaptions] = useState(initialPrefs.withCaptions)
  const [withGemma, setWithGemma] = useState(initialPrefs.withGemma)
  const [quality, setQuality] = useState(initialPrefs.quality)
  const [layout, setLayout] =
    useState<(typeof LAYOUT_OPTIONS)[number]['value']>(initialPrefs.layout)
  const [camZoom, setCamZoom] = useState(1.0)
  const [gameZoom, setGameZoom] = useState(1.0)
  const [gamePan, setGamePan] = useState(0.55)
  const [appliedZoom, setAppliedZoom] = useState(1.0)
  const [appliedPan, setAppliedPan] = useState(0.55)
  const [reframing, setReframing] = useState(false)
  const [captionStyle, setCaptionStyle] = useState<CaptionStyle>(DEFAULT_CAPTION_STYLE)
  const [appliedCaptionStyle, setAppliedCaptionStyle] =
    useState<CaptionStyle>(DEFAULT_CAPTION_STYLE)
  const [captionBusy, setCaptionBusy] = useState(false)
  const [previewNonce, setPreviewNonce] = useState(0)
  const [busy, setBusy] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [jobsList, setJobsList] = useState<Job[]>([])
  const [error, setError] = useState<string | null>(null)
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null)
  const [stopping, setStopping] = useState(false)
  const reframeTimer = useRef<number | null>(null)
  const reframeSeq = useRef(0)
  const skipAutoReframe = useRef(true)
  const syncedJobFraming = useRef<string | null>(null)

  async function refreshJobsList() {
    try {
      const res = await fetch(`${API}/api/jobs`)
      if (!res.ok) return
      const rows: { job: Job }[] = await res.json()
      setJobsList(rows.map((r) => r.job))
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then((r) => r.json())
      .then((data: Health) => setHealth(data))
      .catch(() => setHealth(null))

    fetch(`${API}/api/jobs`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: { job: Job }[]) => {
        const list = rows.map((r) => r.job)
        setJobsList(list)
        const active = list.find((j) => !isTerminal(j.status))
        if (active) setJob(active)
      })
      .catch(() => {
        /* ignore */
      })
  }, [])

  useEffect(() => {
    if (section !== 'jobs' && section !== 'studio') return
    void refreshJobsList()
    const timer = window.setInterval(() => void refreshJobsList(), 4000)
    return () => window.clearInterval(timer)
  }, [section])

  useEffect(() => {
    if (!job?.id || isTerminal(job.status)) return
    const id = job.id
    const timer = window.setInterval(async () => {
      try {
        const res = await fetch(`${API}/api/jobs/${id}`)
        if (!res.ok) return
        const data = await res.json()
        setJob(data.job)
      } catch {
        /* ignore */
      }
    }, 1200)
    return () => window.clearInterval(timer)
  }, [job?.id, job?.status])

  useEffect(() => {
    if (!job?.clips?.length) {
      setSelectedClipId(null)
      return
    }
    if (!selectedClipId || !job.clips.some((c) => c.id === selectedClipId)) {
      setSelectedClipId(job.clips[0].id)
    }
  }, [job, selectedClipId])

  useEffect(() => {
    savePrefs({ layout, quality, withCaptions, withGemma })
  }, [layout, quality, withCaptions, withGemma])

  const statusClass = useMemo(() => {
    if (!job) return ''
    if (job.status === 'done') return 'done'
    if (job.status === 'failed' || job.status === 'cancelled') return 'failed'
    return 'active'
  }, [job])

  const vod = job?.meta?.vod
  const progress = Math.max(0, Math.min(100, job?.meta?.progress ?? 0))
  const railStates = job ? stepStates(job) : []
  const gemmaReady = Boolean(health?.tools?.gemma)
  const gemmaOn = gemmaReady && withGemma
  const selectedClip = job?.clips.find((c) => c.id === selectedClipId) || null
  const readyClips = job?.clips.filter((c) => c.video_path || c.captioned_path) || []
  const captionDirty =
    JSON.stringify(captionStyle) !== JSON.stringify(appliedCaptionStyle)
  const previewSource =
    captionDirty && selectedClip?.video_path
      ? selectedClip.video_path
      : selectedClip?.captioned_path || selectedClip?.video_path || null
  const previewUrl = job
    ? clipMediaUrl(
        job.id,
        previewSource,
        `${job.updated_at || 0}-${previewNonce}`,
      )
    : null
  const activeLayout = (job?.meta?.layout as string) || layout
  const canLiveReframe =
    Boolean(previewUrl) &&
    Boolean(selectedClipId) &&
    Boolean(job?.id) &&
    (activeLayout === 'cam_hook_game' || activeLayout === 'game_hook_cam') &&
    isTerminal(job?.status)
  const framingDirty =
    Math.abs(gameZoom - appliedZoom) > 0.001 ||
    Math.abs(gamePan - appliedPan) > 0.001 ||
    Math.abs(camZoom - (job?.cam_zoom ?? job?.meta?.cam_zoom ?? 1)) > 0.001
  const livePreviewing = framingDirty && !reframing
  const phoneLiveStyle = livePreviewing
    ? ({
        transform: `scale(${1 + (gameZoom - appliedZoom) * 0.75}) translate(${(appliedPan - gamePan) * 22}%, ${(gameZoom - appliedZoom) * 6}%)`,
        transformOrigin: `${gamePan * 100}% 72%`,
      } as CSSProperties)
    : undefined
  const canEditCaptions =
    Boolean(job?.id) &&
    Boolean(selectedClip?.video_path) &&
    isTerminal(job?.status) &&
    Boolean(job?.with_captions !== false)
  const captionOverlayStyle: CSSProperties = {
    color: captionStyle.font_color,
    fontFamily: `"${captionStyle.font_name}", Impact, sans-serif`,
    fontSize: `${Math.max(0.75, captionStyle.font_size / 40)}rem`,
    textTransform: captionStyle.uppercase ? 'uppercase' : 'none',
    ...(captionStyle.alignment === 'bottom'
      ? { bottom: `${6 + captionStyle.margin_v * 0.28}%`, top: 'auto' }
      : captionStyle.alignment === 'top'
        ? { top: `${6 + captionStyle.margin_v * 0.28}%`, bottom: 'auto' }
        : { top: '46%', bottom: 'auto', transform: 'translateY(-50%)' }),
  }
  const cutClips =
    job?.clips.filter((c) =>
      ['cut', 'short', 'captioned', 'ready'].includes(c.status),
    ).length || 0
  const shortClips =
    job?.clips.filter((c) =>
      ['short', 'captioned', 'ready'].includes(c.status),
    ).length || 0
  const captionedClips =
    job?.clips.filter((c) => Boolean(c.captioned_path) || c.status === 'captioned')
      .length || 0
  const pendingClips = job?.clips.filter((c) => c.status === 'pending').length || 0
  const clipProgress = job?.meta?.clip_progress
  const clipTotal = clipProgress?.total || job?.clips.length || 0
  const clipPhase = clipProgress?.phase
  const clipDone =
    clipProgress?.done ??
    (clipPhase === 'shorts' || job?.meta?.stage === 'shorts'
      ? shortClips
      : clipPhase === 'captions' || job?.meta?.stage === 'captioning'
        ? captionedClips
        : cutClips)
  const clipTallyPct =
    clipTotal > 0 ? Math.max(0, Math.min(100, Math.round((clipDone / clipTotal) * 100))) : 0
  const clipsHeadLabel = (() => {
    if (!job?.clips.length) return 'waiting for moments'
    if (job.status === 'done') return `${job.clips.length}/${job.clips.length} ready`
    if (job.meta?.stage === 'shorts' || clipPhase === 'shorts') {
      return `${shortClips}/${job.clips.length} packaged · ${cutClips} cut`
    }
    if (job.meta?.stage === 'captioning' || clipPhase === 'captions') {
      return `${captionedClips}/${job.clips.length} captioned · ${shortClips} shorts`
    }
    if (job.meta?.stage === 'cutting' || clipPhase === 'encode' || clipPhase === 'scene') {
      return `${cutClips}/${job.clips.length} cut · ${pendingClips} waiting`
    }
    return `${readyClips.length}/${job.clips.length} ready · ${cutClips} cut`
  })()

  useEffect(() => {
    if (gemmaReady) setWithGemma(true)
  }, [gemmaReady])

  const coreTools = health
    ? Object.entries(health.tools).filter(([name]) => CORE_ENGINE_KEYS.includes(name))
    : []
  const allTools = health ? Object.entries(health.tools) : []
  const enginesReady = coreTools.filter(([, on]) => on).length
  const pageTitle = NAV_ITEMS.find((n) => n.id === section)?.label || 'Studio'

  async function onSubmit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    setSection('studio')
    try {
      const res = await fetch(`${API}/api/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          with_captions: withCaptions,
          with_gemma: withGemma && gemmaReady,
          max_clips: 12,
          quality,
          layout,
          cam_zoom: camZoom,
          game_zoom: gameZoom,
          game_pan: gamePan,
        }),
      })
      if (!res.ok) {
        let message = 'Failed to start job'
        try {
          const body = await res.json()
          if (typeof body?.detail === 'string') message = body.detail
          else if (Array.isArray(body?.detail))
            message = body.detail
              .map((d: { msg?: string }) => d.msg || '')
              .filter(Boolean)
              .join(' ')
          else message = JSON.stringify(body)
        } catch {
          message = (await res.text()) || message
        }
        throw new Error(message)
      }
      const data = await res.json()
      setJob(data.job)
      setSelectedClipId(null)
      void refreshJobsList()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  async function onReframePhone(opts?: { silent?: boolean }) {
    if (!job?.id || !selectedClipId) {
      if (!opts?.silent) {
        setError('Select a clip first, then move zoom/pan to update the phone')
      }
      return
    }
    const layoutId =
      activeLayout === 'game_hook_cam' || activeLayout === 'cam_hook_game'
        ? activeLayout
        : layout
    if (layoutId !== 'cam_hook_game' && layoutId !== 'game_hook_cam') {
      if (!opts?.silent) setError('Switch to Cam · Hook · Game layout to reframe')
      return
    }
    if (
      Math.abs(gameZoom - appliedZoom) < 0.001 &&
      Math.abs(gamePan - appliedPan) < 0.001 &&
      Math.abs(camZoom - (job.cam_zoom ?? job.meta?.cam_zoom ?? 1)) < 0.001
    ) {
      return
    }
    const seq = ++reframeSeq.current
    setReframing(true)
    setError(null)
    const controller = new AbortController()
    const kill = window.setTimeout(() => controller.abort(), 180_000)
    try {
      const res = await fetch(
        `${API}/api/jobs/${job.id}/clips/${selectedClipId}/reframe`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            cam_zoom: camZoom,
            game_zoom: gameZoom,
            game_pan: gamePan,
            layout: layoutId,
          }),
          signal: controller.signal,
        },
      )
      if (!res.ok) {
        let message = 'Reframe failed'
        try {
          const body = await res.json()
          if (typeof body?.detail === 'string') message = body.detail
        } catch {
          /* ignore */
        }
        throw new Error(message)
      }
      const data = await res.json()
      if (seq !== reframeSeq.current) return
      setJob(data.job)
      setAppliedZoom(gameZoom)
      setAppliedPan(gamePan)
      setPreviewNonce(Date.now())
      setReframing(false)
      // Re-burn captions after crop so the phone is not stuck on "Updating…"
      if (data.job?.with_captions !== false) {
        void (async () => {
          setCaptionBusy(true)
          try {
            const capRes = await fetch(
              `${API}/api/jobs/${job.id}/clips/${selectedClipId}/captions`,
              {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(captionStyle),
              },
            )
            if (!capRes.ok) return
            const capData = await capRes.json()
            if (seq !== reframeSeq.current) return
            setJob(capData.job)
            setAppliedCaptionStyle(captionStyle)
            setPreviewNonce(Date.now())
          } finally {
            if (seq === reframeSeq.current) setCaptionBusy(false)
          }
        })()
      }
    } catch (err) {
      if (seq !== reframeSeq.current) return
      if (err instanceof DOMException && err.name === 'AbortError') {
        setError('Reframe timed out — try again or lower quality')
      } else {
        setError(err instanceof Error ? err.message : 'Reframe failed')
      }
    } finally {
      window.clearTimeout(kill)
      if (seq === reframeSeq.current) setReframing(false)
    }
  }

  async function onApplyCaptions() {
    if (!job?.id || !selectedClipId) {
      setError('Select a clip first')
      return
    }
    setCaptionBusy(true)
    setError(null)
    try {
      const res = await fetch(
        `${API}/api/jobs/${job.id}/clips/${selectedClipId}/captions`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(captionStyle),
        },
      )
      if (!res.ok) {
        let message = 'Caption update failed'
        try {
          const body = await res.json()
          if (typeof body?.detail === 'string') message = body.detail
        } catch {
          /* ignore */
        }
        throw new Error(message)
      }
      const data = await res.json()
      setJob(data.job)
      setAppliedCaptionStyle(captionStyle)
      setPreviewNonce(Date.now())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Caption update failed')
    } finally {
      setCaptionBusy(false)
    }
  }

  useEffect(() => {
    if (!job?.id) return
    if (syncedJobFraming.current === job.id) return
    syncedJobFraming.current = job.id
    const z = Number(job.game_zoom ?? job.meta?.game_zoom ?? 1)
    const p = Number(job.game_pan ?? job.meta?.game_pan ?? 0.55)
    const c = Number(job.cam_zoom ?? job.meta?.cam_zoom ?? 1)
    setGameZoom(z)
    setGamePan(p)
    setCamZoom(c)
    setAppliedZoom(z)
    setAppliedPan(p)
    skipAutoReframe.current = true
    const saved = job.meta?.caption_style
    if (saved && typeof saved === 'object') {
      const next = { ...DEFAULT_CAPTION_STYLE, ...saved } as CaptionStyle
      setCaptionStyle(next)
      setAppliedCaptionStyle(next)
    }
    // Only sync when switching jobs — not on every meta poll tick
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id])

  useEffect(() => {
    if (skipAutoReframe.current) {
      skipAutoReframe.current = false
      return
    }
    if (!canLiveReframe || reframing) return
    if (!framingDirty) return
    if (reframeTimer.current) window.clearTimeout(reframeTimer.current)
    reframeTimer.current = window.setTimeout(() => {
      void onReframePhone({ silent: true })
    }, 900)
    return () => {
      if (reframeTimer.current) window.clearTimeout(reframeTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameZoom, gamePan, camZoom, canLiveReframe, framingDirty])

  async function onStop() {
    setStopping(true)
    setError(null)
    try {
      if (job && !isTerminal(job.status)) {
        const res = await fetch(`${API}/api/jobs/${job.id}/cancel`, { method: 'POST' })
        if (res.ok) {
          const data = await res.json()
          setJob(data.job)
          void refreshJobsList()
          return
        }
      }
      const res = await fetch(`${API}/api/downloads/stop`, { method: 'POST' })
      if (!res.ok) throw new Error('Could not stop download')
      if (job) {
        setJob({
          ...job,
          status: 'cancelled',
          message: 'Stopped',
          error: null,
          meta: {
            ...job.meta,
            stage: 'cancelled',
            activity: 'Stopped — you can start another download',
          },
        })
      }
      void refreshJobsList()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Stop failed')
    } finally {
      setStopping(false)
    }
  }

  function openJob(next: Job) {
    setJob(next)
    setSelectedClipId(null)
    setSection('studio')
    setError(null)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="App navigation">
        <div className="sidebar-brand">
          <span className="mark">CW</span>
          <div>
            <strong>Cliperworld</strong>
            <em>Shorts studio</em>
          </div>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${section === item.id ? 'active' : ''}`}
              onClick={() => setSection(item.id)}
            >
              <strong>{item.label}</strong>
              <span>{item.hint}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <p className="account-slot">
            <strong>Local workspace</strong>
            <span>No account · auth later</span>
          </p>
        </div>
      </aside>

      <div className="app-main">
        <header className="app-topbar">
          <div>
            <p className="topbar-kicker">Cliperworld</p>
            <h1>{pageTitle}</h1>
          </div>
          <div className="topbar-actions">
            <span className={`model-chip ${gemmaReady ? 'on' : 'off'}`}>
              {gemmaReady ? 'Gemma ready' : 'Chat spikes only'}
            </span>
            {health && (
              <span className="model-chip on">
                {enginesReady}/{coreTools.length} engines
              </span>
            )}
            {job && !isTerminal(job.status) && (
              <button
                type="button"
                className="stop-btn"
                onClick={() => void onStop()}
                disabled={stopping}
              >
                {stopping ? 'Stopping…' : 'Stop job'}
              </button>
            )}
          </div>
        </header>

        <main className="app-content">
          {error && section === 'studio' && <p className="error banner-error">{error}</p>}

          {section === 'studio' && (
            <div className="studio-page">
              <section className="panel composer-panel">
                <div className="panel-head">
                  <h2>New Shorts job</h2>
                  <p>Paste a Twitch or YouTube link. Engines find moments and package 9:16.</p>
                </div>
                <form className="composer" onSubmit={onSubmit}>
                  <label htmlFor="vod">Stream or VOD link</label>
                  <div className="row">
                    <input
                      id="vod"
                      type="url"
                      required
                      placeholder="https://www.twitch.tv/…  or  youtube.com/watch?v=…"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                    />
                    <button type="submit" disabled={busy}>
                      {busy ? 'Starting…' : 'Generate clips'}
                    </button>
                  </div>

                  <div className="layout-picker" role="radiogroup" aria-label="Shorts layout">
                    <p className="layout-picker-label">Layout style</p>
                    <div className="layout-grid">
                      {LAYOUT_OPTIONS.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          role="radio"
                          aria-checked={layout === opt.value}
                          className={`layout-card ${layout === opt.value ? 'active' : ''} layout-${opt.value}`}
                          onClick={() => {
                            setLayout(opt.value)
                            if (
                              (opt.value === 'cam_hook_game' ||
                                opt.value === 'game_hook_cam' ||
                                opt.value === 'face') &&
                              (quality === '360' || quality === '480')
                            ) {
                              setQuality('720')
                            }
                          }}
                        >
                          <span className="layout-sketch" aria-hidden>
                            {opt.value === 'blur' && (
                              <>
                                <i className="sk-blur" />
                                <i className="sk-center" />
                              </>
                            )}
                            {opt.value === 'full_hook' && (
                              <>
                                <i className="sk-top-hook" />
                                <i className="sk-plate" />
                                <i className="sk-bottom-bar" />
                              </>
                            )}
                            {opt.value === 'cam_hook_game' && (
                              <>
                                <i className="sk-cam" />
                                <i className="sk-hook" />
                                <i className="sk-game" />
                              </>
                            )}
                            {opt.value === 'game_hook_cam' && (
                              <>
                                <i className="sk-game" />
                                <i className="sk-hook" />
                                <i className="sk-cam" />
                              </>
                            )}
                            {opt.value === 'face' && <i className="sk-face" />}
                          </span>
                          <strong>{opt.label}</strong>
                          <em>{opt.blurb}</em>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="option-rail" role="group" aria-label="Clip options">
                    <label className={`opt ${withCaptions ? 'active' : ''}`}>
                      <input
                        type="checkbox"
                        checked={withCaptions}
                        onChange={(e) => setWithCaptions(e.target.checked)}
                      />
                      Captions
                    </label>
                    <label className="opt active locked" title="Always on">
                      <input type="checkbox" checked readOnly />
                      9:16 Shorts
                    </label>
                    <label
                      className={`opt ${gemmaOn ? 'active' : ''} ${!gemmaReady ? 'locked' : ''}`}
                      title={
                        gemmaReady
                          ? 'Use Gemma to score viral moments + write titles'
                          : 'Waiting for Gemma…'
                      }
                    >
                      <input
                        type="checkbox"
                        checked={gemmaOn}
                        disabled={!gemmaReady}
                        onChange={(e) => setWithGemma(e.target.checked)}
                      />
                      {gemmaReady ? 'Gemma AI picks' : 'Gemma (loading…)'}
                    </label>
                    <label className="quality-field" htmlFor="quality">
                      Quality
                      <select
                        id="quality"
                        value={quality}
                        onChange={(e) => setQuality(e.target.value)}
                      >
                        {QUALITY_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>

                  {(layout === 'cam_hook_game' || layout === 'game_hook_cam') && (
                    <div className="framing-rail" aria-label="Shorts framing">
                      <p className="layout-picker-label">
                        Phone game view · zoom / pan under the cam
                      </p>
                      <div className="framing-sliders framing-sliders-3">
                        <label className="framing-field" htmlFor="cam-zoom">
                          <span>
                            Cam <em>{camZoom.toFixed(2)}×</em>
                          </span>
                          <input
                            id="cam-zoom"
                            type="range"
                            min={0.7}
                            max={1.5}
                            step={0.05}
                            value={camZoom}
                            onChange={(e) => setCamZoom(Number(e.target.value))}
                          />
                          <span className="framing-hints">
                            <i>wider</i>
                            <i>face</i>
                          </span>
                        </label>
                        <label className="framing-field" htmlFor="game-zoom">
                          <span>
                            Game zoom <em>{gameZoom.toFixed(2)}×</em>
                          </span>
                          <input
                            id="game-zoom"
                            type="range"
                            min={1}
                            max={2}
                            step={0.05}
                            value={gameZoom}
                            onChange={(e) => setGameZoom(Number(e.target.value))}
                          />
                          <span className="framing-hints">
                            <i>fill</i>
                            <i>dig in</i>
                          </span>
                        </label>
                        <label className="framing-field" htmlFor="game-pan">
                          <span>
                            Game pan{' '}
                            <em>
                              {gamePan < 0.45 ? 'left' : gamePan > 0.55 ? 'right' : 'center'}
                            </em>
                          </span>
                          <input
                            id="game-pan"
                            type="range"
                            min={0}
                            max={1}
                            step={0.05}
                            value={gamePan}
                            onChange={(e) => setGamePan(Number(e.target.value))}
                          />
                          <span className="framing-hints">
                            <i>← left</i>
                            <i>right →</i>
                          </span>
                        </label>
                      </div>
                    </div>
                  )}
                </form>
              </section>

              {!job && (
                <section className="panel empty-studio">
                  <div className="empty-phone" aria-hidden>
                    <div className="phone">
                      <div className="phone-notch" />
                      <div className="phone-screen">
                        <div className={`phone-layout-mock layout-${layout}`}>
                          {layout === 'cam_hook_game' && (
                            <>
                              <div className="sk-cam">
                                <span>Facecam</span>
                              </div>
                              <div className="sk-hook">
                                <span>HOOK</span>
                              </div>
                              <div className="sk-game">
                                <span>Gameplay</span>
                              </div>
                            </>
                          )}
                          {layout === 'game_hook_cam' && (
                            <>
                              <div className="sk-game">
                                <span>Gameplay</span>
                              </div>
                              <div className="sk-hook">
                                <span>HOOK</span>
                              </div>
                              <div className="sk-cam">
                                <span>Facecam</span>
                              </div>
                            </>
                          )}
                          {layout === 'face' && (
                            <div className="sk-face-wrap">
                              <div className="sk-face" />
                              <span>Face track</span>
                            </div>
                          )}
                          {layout === 'blur' && (
                            <div className="sk-blur-wrap">
                              <i className="sk-blur" />
                              <i className="sk-center" />
                              <span>Blur fill</span>
                            </div>
                          )}
                          {layout === 'full_hook' && (
                            <div className="sk-full-hook-wrap">
                              <div className="sk-top-hook">
                                <span>Explain hook</span>
                              </div>
                              <div className="sk-plate">
                                <span>Full 16:9</span>
                              </div>
                              <div className="sk-bottom-bar" />
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div>
                    <h2>Ready when you are</h2>
                    <p>
                      Jobs appear here with cover, pipeline progress, phone preview, and
                      downloadable Shorts.
                    </p>
                  </div>
                </section>
              )}

              {job && (
                <section className="workspace">
                  <div className="studio">
                    <div className="studio-main">
                      <div className="cover-panel panel">
                        <div className="cover-frame">
                          {vod?.thumbnail ? (
                            <img src={vod.thumbnail} alt={vod.title || 'VOD cover'} />
                          ) : (
                            <div className="cover-skeleton">
                              <span>Fetching cover…</span>
                            </div>
                          )}
                          {!isTerminal(job.status) && (
                            <div className="cover-live">Live</div>
                          )}
                        </div>
                        <div className="cover-meta">
                          <p className="streamer">
                            {vod?.streamer || job.platform || 'Stream'}
                          </p>
                          <h2>{vod?.title || `Video ${job.vod_id || '…'}`}</h2>
                          <div className="cover-stats">
                            {vod?.length_label && <span>{vod.length_label}</span>}
                            {vod?.category && <span>{vod.category}</span>}
                            {typeof vod?.views === 'number' && (
                              <span>{vod.views.toLocaleString()} views</span>
                            )}
                            {job.meta?.picker && <span>picker · {job.meta.picker}</span>}
                            <span>layout · {job.meta?.layout || layout}</span>
                            {job.meta?.format && <span>{job.meta.format}</span>}
                          </div>
                        </div>
                      </div>

                      <div className="work-panel panel">
                        <div className={`status ${statusClass}`}>
                          <div className="status-row">
                            <strong>{statusHeadline(job)}</strong>
                            <div className="status-actions">
                              <span className="pct-badge">{progress}%</span>
                              {!isTerminal(job.status) && (
                                <button
                                  type="button"
                                  className="stop-btn"
                                  onClick={() => void onStop()}
                                  disabled={stopping}
                                >
                                  {stopping ? 'Stopping…' : 'Stop'}
                                </button>
                              )}
                            </div>
                          </div>
                          <span>{job.message}</span>
                          {job.error && <span className="status-error">{job.error}</span>}
                        </div>

                        <div className="progress-track" aria-label="Job progress">
                          <div className="progress-bar" style={{ width: `${progress}%` }} />
                        </div>
                        <p className="progress-label">
                          <em>{progress}%</em>
                          <span>{job.meta?.activity || 'Starting'}</span>
                        </p>
                        {clipTotal > 0 && !isTerminal(job.status) && (
                          <div className="clip-tally" aria-label="Clip tally">
                            <div className="clip-tally-track">
                              <div
                                className="clip-tally-bar"
                                style={{ width: `${clipTallyPct}%` }}
                              />
                            </div>
                            <p className="clip-tally-label">
                              {clipProgress?.label ||
                                `${cutClips}/${clipTotal} clips through Cut`}
                              {pendingClips > 0 ? ` · ${pendingClips} waiting` : ''}
                            </p>
                          </div>
                        )}

                        <ol className="steps" aria-label="Pipeline stages">
                          {STAGES.map((stage, idx) => {
                            const state = railStates[idx] || 'todo'
                            const isCurrent = state === 'current'
                            return (
                              <li
                                key={stage.id}
                                className={`step ${state}`}
                                title={
                                  isCurrent
                                    ? `${stage.label} · ${progress}% · ${job.meta?.activity || job.message}`
                                    : stage.label
                                }
                              >
                                <span className="step-dot" aria-hidden />
                                <span className="step-label">{stage.label}</span>
                                {isCurrent && (
                                  <span className="step-live">{progress}%</span>
                                )}
                                {state === 'skip' && (
                                  <span className="step-live">off</span>
                                )}
                              </li>
                            )
                          })}
                        </ol>

                        {job.meta?.caption_error && (
                          <p className="error">Captions: {job.meta.caption_error}</p>
                        )}
                        {job.meta?.gemma_error && (
                          <p className="waiting">Gemma soft-skip: {job.meta.gemma_error}</p>
                        )}
                        {job.meta?.gemma_hint && !gemmaOn && (
                          <p className="waiting">{job.meta.gemma_hint}</p>
                        )}
                      </div>
                    </div>

                    <aside className="phone-stage" aria-label="Shorts preview">
                      <div className="phone">
                        <div className="phone-notch" />
                        <div className="phone-screen">
                          {previewUrl ? (
                            <>
                              <video
                                key={previewUrl}
                                className={`phone-video${livePreviewing || reframing ? ' phone-video-live' : ''}`}
                                src={previewUrl}
                                controls
                                playsInline
                                autoPlay
                                muted
                                loop
                                style={phoneLiveStyle}
                              />
                              {captionDirty && (
                                <div
                                  className="phone-caption-overlay"
                                  style={captionOverlayStyle}
                                  aria-hidden
                                >
                                  <span style={{ color: captionStyle.highlight_color }}>
                                    {captionStyle.uppercase ? 'TO DATE' : 'To date'}
                                  </span>{' '}
                                  <span>or</span>
                                </div>
                              )}
                              {reframing && (
                                <div className="phone-updating" aria-live="polite">
                                  Rendering crop…
                                </div>
                              )}
                              {livePreviewing && !reframing && (
                                <div className="phone-updating soft" aria-live="polite">
                                  Live preview
                                </div>
                              )}
                            </>
                          ) : (
                            <>
                              {vod?.thumbnail && (
                                <img src={vod.thumbnail} alt="" className="phone-bg" />
                              )}
                              <div
                                className={`phone-layout-mock layout-${activeLayout}`}
                                aria-hidden
                                style={
                                  {
                                    '--cam-zoom': String(camZoom),
                                    '--game-zoom': String(gameZoom),
                                  } as CSSProperties
                                }
                              >
                                {activeLayout === 'cam_hook_game' && (
                                  <>
                                    <div className="sk-cam sk-zoom-cam">
                                      <span>Facecam</span>
                                    </div>
                                    <div className="sk-hook">
                                      <span>HOOK</span>
                                    </div>
                                    <div className="sk-game sk-zoom-game">
                                      <span>Gameplay</span>
                                    </div>
                                  </>
                                )}
                                {activeLayout === 'game_hook_cam' && (
                                  <>
                                    <div className="sk-game sk-zoom-game">
                                      <span>Gameplay</span>
                                    </div>
                                    <div className="sk-hook">
                                      <span>HOOK</span>
                                    </div>
                                    <div className="sk-cam sk-zoom-cam">
                                      <span>Facecam</span>
                                    </div>
                                  </>
                                )}
                                {activeLayout === 'face' && (
                                  <div className="sk-face-wrap">
                                    <div className="sk-face" />
                                    <span>Face track</span>
                                  </div>
                                )}
                                {activeLayout === 'blur' && (
                                  <div className="sk-blur-wrap">
                                    <i className="sk-blur" />
                                    <i className="sk-center" />
                                    <span>Blur fill</span>
                                  </div>
                                )}
                                {activeLayout === 'full_hook' && (
                                  <div className="sk-full-hook-wrap">
                                    <div className="sk-top-hook">
                                      <span>Explain hook</span>
                                    </div>
                                    <div className="sk-plate">
                                      <span>Full 16:9</span>
                                    </div>
                                    <div className="sk-bottom-bar" />
                                  </div>
                                )}
                              </div>
                              <div className="phone-overlay phone-overlay-compact">
                                <p className="phone-kicker">Short preview</p>
                                <strong>
                                  {LAYOUT_OPTIONS.find((o) => o.value === activeLayout)
                                    ?.label || 'Layout'}
                                </strong>
                                <span>
                                  {job.status === 'downloading' ||
                                  job.meta?.stage?.includes('download')
                                    ? `${progress}% · still downloading`
                                    : selectedClip
                                      ? `${formatTime(selectedClip.start)} → ${formatTime(selectedClip.end)}`
                                      : 'Short plays after Cut + 9:16'}
                                </span>
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                      <p className="phone-caption">
                        {previewUrl
                          ? 'Playing selected Short · tap clip cards to switch'
                          : `${LAYOUT_OPTIONS.find((o) => o.value === activeLayout)?.blurb || '9:16'} · preview fills when ready`}
                      </p>
                      {(activeLayout === 'cam_hook_game' ||
                        activeLayout === 'game_hook_cam') &&
                        previewUrl && (
                          <div className="phone-reframe">
                            <p className="layout-picker-label">
                              Adjust game view · phone updates live
                            </p>
                            <label className="framing-field" htmlFor="phone-game-zoom">
                              <span>
                                Zoom <em>{gameZoom.toFixed(2)}×</em>
                              </span>
                              <input
                                id="phone-game-zoom"
                                type="range"
                                min={1}
                                max={2}
                                step={0.05}
                                value={gameZoom}
                                disabled={!canLiveReframe && !isTerminal(job?.status)}
                                onInput={(e) =>
                                  setGameZoom(
                                    Number((e.target as HTMLInputElement).value),
                                  )
                                }
                                onChange={(e) => setGameZoom(Number(e.target.value))}
                              />
                            </label>
                            <label className="framing-field" htmlFor="phone-game-pan">
                              <span>
                                Pan{' '}
                                <em>
                                  {gamePan < 0.45
                                    ? 'left'
                                    : gamePan > 0.55
                                      ? 'right'
                                      : 'center'}
                                </em>
                              </span>
                              <input
                                id="phone-game-pan"
                                type="range"
                                min={0}
                                max={1}
                                step={0.05}
                                value={gamePan}
                                disabled={!canLiveReframe && !isTerminal(job?.status)}
                                onInput={(e) =>
                                  setGamePan(
                                    Number((e.target as HTMLInputElement).value),
                                  )
                                }
                                onChange={(e) => setGamePan(Number(e.target.value))}
                              />
                            </label>
                            <p className="phone-reframe-hint">
                              {reframing
                                ? 'Re-encoding crop (can take a minute)…'
                                : framingDirty
                                  ? 'Live preview · apply after you pause dragging'
                                  : canLiveReframe
                                    ? 'Drag zoom/pan · renders only when values change'
                                    : 'Finish the job first, then drag to reframe'}
                            </p>
                            {framingDirty && !reframing && (
                              <button
                                type="button"
                                className="ghost-btn apply-btn"
                                onClick={() => void onReframePhone()}
                              >
                                Apply framing
                              </button>
                            )}
                          </div>
                        )}
                      {canEditCaptions && previewUrl && (
                        <div className="phone-reframe caption-style">
                          <p className="layout-picker-label">Captions · move & style</p>
                          <div className="caption-presets">
                            {CAPTION_PRESETS.map((preset) => (
                              <button
                                key={preset.id}
                                type="button"
                                className={`opt${
                                  captionStyle.font_name === preset.style.font_name &&
                                  captionStyle.highlight_color ===
                                    preset.style.highlight_color &&
                                  captionStyle.alignment === preset.style.alignment
                                    ? ' active'
                                    : ''
                                }`}
                                onClick={() =>
                                  setCaptionStyle({
                                    ...DEFAULT_CAPTION_STYLE,
                                    ...preset.style,
                                  } as CaptionStyle)
                                }
                              >
                                {preset.label}
                              </button>
                            ))}
                          </div>
                          <label className="framing-field" htmlFor="cap-pos">
                            <span>
                              Position{' '}
                              <em>
                                {captionStyle.alignment}
                                {' · '}
                                {captionStyle.margin_v}
                              </em>
                            </span>
                            <select
                              id="cap-pos"
                              value={captionStyle.alignment}
                              onChange={(e) =>
                                setCaptionStyle((s) => ({
                                  ...s,
                                  alignment: e.target.value as CaptionStyle['alignment'],
                                }))
                              }
                            >
                              <option value="top">Top</option>
                              <option value="middle">Middle</option>
                              <option value="bottom">Bottom</option>
                            </select>
                          </label>
                          <label className="framing-field" htmlFor="cap-margin">
                            <span>
                              Offset from edge <em>{captionStyle.margin_v}</em>
                            </span>
                            <input
                              id="cap-margin"
                              type="range"
                              min={8}
                              max={100}
                              step={1}
                              value={captionStyle.margin_v}
                              onChange={(e) =>
                                setCaptionStyle((s) => ({
                                  ...s,
                                  margin_v: Number(e.target.value),
                                }))
                              }
                            />
                          </label>
                          <label className="framing-field" htmlFor="cap-font">
                            <span>Font style</span>
                            <select
                              id="cap-font"
                              value={captionStyle.font_name}
                              onChange={(e) =>
                                setCaptionStyle((s) => ({
                                  ...s,
                                  font_name: e.target.value,
                                }))
                              }
                            >
                              {CAPTION_FONTS.map((f) => (
                                <option key={f.value} value={f.value}>
                                  {f.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="framing-field" htmlFor="cap-size">
                            <span>
                              Size <em>{captionStyle.font_size}</em>
                            </span>
                            <input
                              id="cap-size"
                              type="range"
                              min={24}
                              max={72}
                              step={2}
                              value={captionStyle.font_size}
                              onChange={(e) =>
                                setCaptionStyle((s) => ({
                                  ...s,
                                  font_size: Number(e.target.value),
                                }))
                              }
                            />
                          </label>
                          <div className="caption-colors">
                            <label className="framing-field" htmlFor="cap-color">
                              <span>Text</span>
                              <input
                                id="cap-color"
                                type="color"
                                value={captionStyle.font_color}
                                onChange={(e) =>
                                  setCaptionStyle((s) => ({
                                    ...s,
                                    font_color: e.target.value,
                                  }))
                                }
                              />
                            </label>
                            <label className="framing-field" htmlFor="cap-hi">
                              <span>Highlight</span>
                              <input
                                id="cap-hi"
                                type="color"
                                value={captionStyle.highlight_color}
                                onChange={(e) =>
                                  setCaptionStyle((s) => ({
                                    ...s,
                                    highlight_color: e.target.value,
                                  }))
                                }
                              />
                            </label>
                          </div>
                          <label className="opt">
                            <input
                              type="checkbox"
                              checked={captionStyle.uppercase}
                              onChange={(e) =>
                                setCaptionStyle((s) => ({
                                  ...s,
                                  uppercase: e.target.checked,
                                }))
                              }
                            />
                            ALL CAPS
                          </label>
                          <p className="phone-reframe-hint">
                            {captionBusy
                              ? 'Burning new caption look…'
                              : captionDirty
                                ? 'Live overlay on phone · Apply to burn into the Short'
                                : 'Tweaks appear live · Apply writes the download file'}
                          </p>
                          <button
                            type="button"
                            className="ghost-btn apply-btn"
                            disabled={!captionDirty || captionBusy}
                            onClick={() => void onApplyCaptions()}
                          >
                            {captionBusy ? 'Applying…' : 'Apply captions'}
                          </button>
                        </div>
                      )}
                    </aside>
                  </div>

                  <div className="clips-head">
                    <h3>
                      Clips <span>{clipsHeadLabel}</span>
                    </h3>
                  </div>

                  <div className="clips">
                    {job.clips.length === 0 && !isTerminal(job.status) && (
                      <p className="waiting">
                        {job.status === 'downloading' ||
                        job.meta?.stage === 'downloading_video' ||
                        job.meta?.stage === 'downloading_chat'
                          ? `Still ${job.meta?.stage?.replaceAll('_', ' ') || 'downloading'} (${progress}%).`
                          : job.meta?.stage === 'analyzing_chat' ||
                              job.meta?.stage === 'gemma'
                            ? 'Finding blow-up moments…'
                            : 'Moments appear after chat spikes or Gemma scoring.'}
                      </p>
                    )}
                    {job.clips.map((clip, index) => {
                      const selected = clip.id === selectedClipId
                      const ready = Boolean(clip.video_path || clip.captioned_path)
                      const isCurrent =
                        !isTerminal(job.status) &&
                        clipProgress?.index === index + 1 &&
                        clip.status === 'pending'
                      return (
                        <article
                          key={clip.id}
                          className={`clip ${selected ? 'selected' : ''} ${ready ? 'ready' : ''} ${isCurrent ? 'working' : ''}`}
                          onClick={() => setSelectedClipId(clip.id)}
                        >
                          <div className="clip-rank">
                            {String(index + 1).padStart(2, '0')}
                          </div>
                          <div className="clip-body">
                            <div className="clip-head">
                              <strong>
                                {clip.title ||
                                  `${formatTime(clip.start)} → ${formatTime(clip.end)}`}
                              </strong>
                              <span className={`score status-${clip.status}`}>
                                {isCurrent
                                  ? `WORKING · ${clipProgress?.phase || 'cut'}`
                                  : `${Math.round(clip.score)} · ${clip.source || 'chat'} · ${clip.status}`}
                              </span>
                            </div>
                            {clip.hook && <p className="clip-hook">{clip.hook}</p>}
                            {clip.hashtags && clip.hashtags.length > 0 && (
                              <p className="clip-tags">{clip.hashtags.join(' ')}</p>
                            )}
                            {clip.sample_messages?.length > 0 && (
                              <ul className="messages">
                                {clip.sample_messages.slice(0, 3).map((m, i) => (
                                  <li key={`${clip.id}-${i}`}>{m}</li>
                                ))}
                              </ul>
                            )}
                            {ready && (
                              <div className="actions">
                                <a
                                  href={`${API}/api/jobs/${job.id}/clips/${clip.id}/download`}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  {clip.captioned_path
                                    ? 'Download captioned Short'
                                    : 'Download Short'}
                                </a>
                              </div>
                            )}
                          </div>
                          <div className="clip-phone-mini" aria-hidden>
                            <span>{formatTime(clip.end - clip.start)}</span>
                          </div>
                        </article>
                      )
                    })}
                  </div>
                </section>
              )}
            </div>
          )}

          {section === 'jobs' && (
            <section className="panel jobs-panel">
              <div className="panel-head">
                <h2>Jobs</h2>
                <p>Open any job to resume preview and downloads in Studio.</p>
              </div>
              {jobsList.length === 0 ? (
                <p className="waiting">No jobs yet. Create one from Studio.</p>
              ) : (
                <div className="jobs-table" role="table">
                  <div className="jobs-row jobs-head" role="row">
                    <span>Title</span>
                    <span>Status</span>
                    <span>Layout</span>
                    <span>Progress</span>
                    <span>Clips</span>
                  </div>
                  {jobsList.map((row) => {
                    const pct = Math.max(0, Math.min(100, row.meta?.progress ?? 0))
                    const active = job?.id === row.id
                    return (
                      <button
                        key={row.id}
                        type="button"
                        className={`jobs-row ${active ? 'active' : ''} status-${row.status}`}
                        onClick={() => openJob(row)}
                      >
                        <span className="jobs-title">
                          <strong>{jobTitle(row)}</strong>
                          <em>{row.id}</em>
                        </span>
                        <span className={`jobs-status status-${row.status}`}>
                          {row.status}
                        </span>
                        <span>{row.meta?.layout || row.layout || '—'}</span>
                        <span>{pct}%</span>
                        <span>{row.clips?.length || 0}</span>
                      </button>
                    )
                  })}
                </div>
              )}
            </section>
          )}

          {section === 'engines' && (
            <section className="panel engines-panel">
              <div className="panel-head">
                <h2>Engines</h2>
                <p>
                  Vendor tools powering download, cut, 9:16, and captions. No rewrite —
                  health from the API.
                </p>
              </div>
              <div className="engines-grid">
                {(allTools.length ? allTools : coreTools).map(([name, on]) => (
                  <div key={name} className={`engine-card ${on ? 'on' : 'off'}`}>
                    <strong>{toolLabel(name)}</strong>
                    <span>{on ? 'Ready' : 'Missing'}</span>
                  </div>
                ))}
              </div>
              {!health && <p className="waiting">Could not reach API health.</p>}
            </section>
          )}

          {section === 'settings' && (
            <section className="panel settings-panel">
              <div className="panel-head">
                <h2>Settings</h2>
                <p>Defaults for new jobs. Saved in this browser only.</p>
              </div>
              <div className="settings-grid">
                <label className="settings-field">
                  Preferred layout
                  <select
                    value={layout}
                    onChange={(e) =>
                      setLayout(e.target.value as (typeof LAYOUT_OPTIONS)[number]['value'])
                    }
                  >
                    {LAYOUT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="settings-field">
                  Default quality
                  <select value={quality} onChange={(e) => setQuality(e.target.value)}>
                    {QUALITY_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={`opt ${withCaptions ? 'active' : ''}`}>
                  <input
                    type="checkbox"
                    checked={withCaptions}
                    onChange={(e) => setWithCaptions(e.target.checked)}
                  />
                  Captions on by default
                </label>
                <label
                  className={`opt ${withGemma ? 'active' : ''} ${!gemmaReady ? 'locked' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={withGemma}
                    disabled={!gemmaReady}
                    onChange={(e) => setWithGemma(e.target.checked)}
                  />
                  Gemma AI picks on by default
                </label>
              </div>

              <div className="account-coming">
                <strong>Account</strong>
                <p>Coming with SaaS auth — sign-in, billing, and team workspaces.</p>
                <button type="button" className="ghost-btn" disabled>
                  Sign in later
                </button>
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  )
}
