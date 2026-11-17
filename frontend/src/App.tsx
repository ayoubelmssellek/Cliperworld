import { useEffect, useMemo, useState, type SubmitEvent } from 'react'
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
  vod_id?: string | null
  platform?: string
  meta?: {
    stage?: string
    progress?: number
    activity?: string
    spike_count?: number
    vod?: VodInfo
    download?: {
      bytes_label?: string
      phase?: string
      line?: string
    }
  }
}

type Health = {
  ok: boolean
  app: string
  tools: Tools
}

const API = import.meta.env.VITE_API_URL ?? ''

const STAGES = [
  { id: 'info', label: 'Cover' },
  { id: 'downloading_video', label: 'Video' },
  { id: 'downloading_chat', label: 'Chat' },
  { id: 'analyzing_chat', label: 'Spikes' },
  { id: 'cutting', label: 'Cut' },
  { id: 'captioning', label: 'Captions' },
  { id: 'done', label: 'Done' },
] as const

function formatTime(seconds: number) {
  const s = Math.max(0, Math.floor(seconds))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${r.toString().padStart(2, '0')}`
}

function stageIndex(stage?: string) {
  if (!stage) return 0
  if (stage === 'failed') return -1
  if (stage === 'downloading') return 1
  const idx = STAGES.findIndex((s) => s.id === stage)
  return idx >= 0 ? idx : 0
}

export default function App() {
  const [url, setUrl] = useState('')
  const [withCaptions, setWithCaptions] = useState(true)
  const [busy, setBusy] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showAllTools, setShowAllTools] = useState(false)

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then((r) => r.json())
      .then((data: Health) => setHealth(data))
      .catch(() => setHealth(null))
  }, [])

  useEffect(() => {
    if (!job || job.status === 'done' || job.status === 'failed') return
    const timer = window.setInterval(async () => {
      try {
        const res = await fetch(`${API}/api/jobs/${job.id}`)
        if (!res.ok) return
        const data = await res.json()
        setJob(data.job)
      } catch {
        /* ignore transient poll errors */
      }
    }, 1500)
    return () => window.clearInterval(timer)
  }, [job])

  const statusClass = useMemo(() => {
    if (!job) return ''
    if (job.status === 'done') return 'done'
    if (job.status === 'failed') return 'failed'
    return 'active'
  }, [job])

  const vod = job?.meta?.vod
  const progress = Math.max(0, Math.min(100, job?.meta?.progress ?? 0))
  const activeStage = stageIndex(job?.meta?.stage || job?.status)
  const coreTools = health
    ? Object.entries(health.tools).filter(([name]) =>
        ['ffmpeg', 'twitch_downloader', 'yt_dlp', 'openshorts', 'whisperx', 'auto_editor'].includes(
          name,
        ),
      )
    : []
  const toolEntries = showAllTools && health ? Object.entries(health.tools) : coreTools

  async function onSubmit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const res = await fetch(`${API}/api/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, with_captions: withCaptions, max_clips: 12 }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Failed to start job')
      }
      const data = await res.json()
      setJob(data.job)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`shell ${job ? 'shell-working' : ''}`}>
      <header className="hero">
        <h1 className="brand">
          Cliper<span>world</span>
        </h1>
        <p className="tagline">
          Paste a Twitch VOD or YouTube link. We find chat blow-ups (or loud
          moments), cut clips, and package them for Shorts.
        </p>

        <form className="composer" onSubmit={onSubmit}>
          <label htmlFor="vod">Twitch or YouTube link</label>
          <div className="row">
            <input
              id="vod"
              type="url"
              required
              placeholder="https://www.twitch.tv/videos/… or https://youtube.com/watch?v=…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <button type="submit" disabled={busy}>
              {busy ? 'Starting…' : 'Find clips'}
            </button>
          </div>
          <div className="meta-row">
            <label>
              <input
                type="checkbox"
                checked={withCaptions}
                onChange={(e) => setWithCaptions(e.target.checked)}
              />
              Try captions
            </label>
            <span className="meta-note">Twitch + YouTube · Kick next</span>
          </div>
        </form>

        {health && (
          <div className="tools" aria-label="Tool availability">
            {toolEntries.map(([name, on]) => (
              <span key={name} className={`pill ${on ? 'on' : 'off'}`}>
                {name.replaceAll('_', ' ')}: {on ? 'ready' : 'missing'}
              </span>
            ))}
            <button
              type="button"
              className="tools-toggle"
              onClick={() => setShowAllTools((v) => !v)}
            >
              {showAllTools ? 'Less' : 'All tools'}
            </button>
          </div>
        )}
      </header>

      {(job || error) && (
        <section className="workspace">
          {error && <p className="error">{error}</p>}

          {job && (
            <>
              <div className="workspace-grid">
                <div className="cover-panel">
                  <div className="cover-frame">
                    {vod?.thumbnail ? (
                      <img src={vod.thumbnail} alt={vod.title || 'VOD cover'} />
                    ) : (
                      <div className="cover-skeleton">
                        <span>Fetching cover…</span>
                      </div>
                    )}
                    {job.status !== 'done' && job.status !== 'failed' && (
                      <div className="cover-live">Working</div>
                    )}
                  </div>
                  <div className="cover-meta">
                    <p className="streamer">{vod?.streamer || job.platform || 'Stream'}</p>
                    <h2>{vod?.title || `Video ${job.vod_id || '…'}`}</h2>
                    <div className="cover-stats">
                      {vod?.length_label && <span>{vod.length_label}</span>}
                      {vod?.category && <span>{vod.category}</span>}
                      {typeof vod?.views === 'number' && (
                        <span>{vod.views.toLocaleString()} views</span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="work-panel">
                  <div className={`status ${statusClass}`}>
                    <strong>{job.status.replaceAll('_', ' ')}</strong>
                    <span>{job.message}</span>
                  </div>

                  <div className="progress-track" aria-label="Job progress">
                    <div className="progress-bar" style={{ width: `${progress}%` }} />
                  </div>
                  <p className="progress-label">{progress}% · {job.meta?.activity || 'Starting'}</p>

                  <ol className="steps">
                    {STAGES.map((stage, idx) => {
                      let state = 'todo'
                      if (job.status === 'failed' && idx <= Math.max(activeStage, 0)) state = 'fail'
                      else if (activeStage > idx || job.status === 'done') state = 'done'
                      else if (activeStage === idx) state = 'current'
                      return (
                        <li key={stage.id} className={`step ${state}`}>
                          <span className="step-dot" />
                          <span>{stage.label}</span>
                        </li>
                      )
                    })}
                  </ol>

                  {job.error && <p className="error">{job.error}</p>}
                </div>
              </div>

              <div className="clips">
                {job.clips.length === 0 && job.status !== 'done' && job.status !== 'failed' && (
                  <p className="waiting">Clips will appear here after chat spikes are found.</p>
                )}
                {job.clips.map((clip) => (
                  <article key={clip.id} className="clip">
                    <div className="clip-head">
                      <strong>
                        {formatTime(clip.start)} → {formatTime(clip.end)}
                      </strong>
                      <span className="score">
                        score {clip.score} · peak {formatTime(clip.peak_second)} · {clip.status}
                      </span>
                    </div>
                    {clip.sample_messages?.length > 0 && (
                      <ul className="messages">
                        {clip.sample_messages.map((m, i) => (
                          <li key={`${clip.id}-${i}`}>{m}</li>
                        ))}
                      </ul>
                    )}
                    {(clip.video_path || clip.captioned_path) && (
                      <div className="actions">
                        <a href={`${API}/api/jobs/${job.id}/clips/${clip.id}/download`}>
                          Download clip
                        </a>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      <p className="foot">
        Stack: TwitchDownloader · yt-dlp · OpenShorts · WhisperX · FFmpeg ·
        Auto-Editor · PySceneDetect. Only clip creators who allow it.
      </p>
    </div>
  )
}