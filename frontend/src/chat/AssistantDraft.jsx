import React, { useState } from 'react'
import { buildSkill, DEFAULT_LIMITS, DRAFT_MAX, sampleAnswer, slug, validateDraft } from './skillFile'

function Field({ label, hint, error, children }) {
  return (
    <label className="msc-field">
      <span>{label}</span>
      {hint && <small>{hint}</small>}
      {children}
      {error && <em role="alert">{error}</em>}
    </label>
  )
}

export function DraftBuilder({ topic, onBuild, onCancel, disabled }) {
  const [draft, setDraft] = useState({
    name: topic ? `${topic} helper`.slice(0, DRAFT_MAX.name) : 'Staff helper',
    purpose: topic ? `Help my staff with: ${topic.toLowerCase()}.` : '',
    knowledge: '',
    limits: DEFAULT_LIMITS,
    question: '',
  })
  const [errors, setErrors] = useState({})
  const update = (field) => (event) => {
    setDraft((current) => ({ ...current, [field]: event.target.value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
  }

  function submit(event) {
    event.preventDefault()
    const found = validateDraft(draft)
    setErrors(found)
    if (!Object.keys(found).length) onBuild(draft)
  }

  return (
    <form className="msc-extra msc-builder" onSubmit={submit} noValidate>
      <p className="msc-extra-title">Build a custom assistant</p>
      <p className="msc-note">Three quick answers. You'll get a draft to review, not a live tool. Don't add customer or staff personal details.</p>
      <Field label="Name" error={errors.name}><input value={draft.name} maxLength={DRAFT_MAX.name} onChange={update('name')} /></Field>
      <Field label="What should it help with?" error={errors.purpose}>
        <input value={draft.purpose} maxLength={DRAFT_MAX.purpose} onChange={update('purpose')} placeholder="Answer new baristas' questions about our drinks" />
      </Field>
      <Field label="What should it know?" hint="Paste recipes, steps or common answers, one per line." error={errors.knowledge}>
        <textarea rows={4} value={draft.knowledge} maxLength={DRAFT_MAX.knowledge} onChange={update('knowledge')} placeholder="Large oat latte: 3 shots and 14 oz steamed oat milk." />
      </Field>
      <Field label="What should it never do?" error={errors.limits}><textarea rows={2} value={draft.limits} maxLength={DRAFT_MAX.limits} onChange={update('limits')} /></Field>
      <Field label="A question to test it (optional)" error={errors.question}>
        <input value={draft.question} maxLength={DRAFT_MAX.question} onChange={update('question')} placeholder="How do I make a large oat latte?" />
      </Field>
      <div className="msc-chips">
        <button type="submit" className="msc-chip-main" disabled={disabled}>Create my draft</button>
        <button type="button" onClick={onCancel} disabled={disabled}>Not now</button>
      </div>
    </form>
  )
}

export function DraftCard({ draft }) {
  const [state, setState] = useState('')
  const skill = buildSkill(draft)
  const sample = draft.question.trim() ? sampleAnswer(draft.knowledge, draft.question) : null

  function download() {
    try {
      const url = URL.createObjectURL(new Blob([skill], { type: 'text/markdown' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `${slug(draft.name)}-SKILL.md`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setState('Downloaded')
    } catch {
      setState("Couldn't download. Copy it instead.")
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(skill)
      setState('Copied')
    } catch {
      setState("Couldn't copy. Download it instead.")
    }
  }

  return (
    <div className="msc-result">
      <div className="msc-answer msc-answer-win">
        <h3>{draft.name}</h3>
        <p>{draft.purpose}</p>
        <p className="msc-note">Draft only. Nothing is saved, connected or live yet.</p>
      </div>
      <article className="msc-option">
        <h5 className="msc-list-title">How it works</h5>
        <ul className="msc-facts">
          <li><span className="msc-fact-label">Input</span><span>A staff question, in plain words</span></li>
          <li><span className="msc-fact-label">Output</span><span>Short steps from your notes, or "ask a manager"</span></li>
          <li><span className="msc-fact-label">Knows</span><span>{draft.knowledge.trim().split(/\n+/).length} lines of your notes</span></li>
          <li><span className="msc-fact-label">Limits</span><span>{draft.limits}</span></li>
        </ul>
        {draft.question.trim() && (
          <>
            <h5 className="msc-list-title">Test question</h5>
            <p className="msc-sample-q">{draft.question}</p>
            <p className="msc-sample-a">{sample ? `From your notes: "${sample}"` : "That's not in your notes, so it would say: I don't know that one. Please ask a manager."}</p>
          </>
        )}
      </article>
      <div className="msc-extra">
        <p className="msc-extra-title">Next steps</p>
        <ol className="msc-steps">
          <li>Read the draft and fix anything that's wrong.</li>
          <li>Try a few real staff questions with it.</li>
          <li>Load the SKILL.md file into an AI assistant your team already uses.</li>
        </ol>
        <div className="msc-chips">
          <button type="button" className="msc-chip-main" onClick={download}>Download SKILL.md</button>
          <button type="button" onClick={copy}>Copy</button>
          <span role="status" className="msc-note">{state}</span>
        </div>
      </div>
    </div>
  )
}
