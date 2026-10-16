import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../ui'

function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-white px-4 py-8">
      <div className="mx-auto max-w-2xl space-y-4 text-sm leading-relaxed text-slate-700">
        <Link to="/">
          <Logo />
        </Link>
        <h1 className="pt-4 text-2xl font-bold text-slate-900">{title}</h1>
        {children}
      </div>
    </div>
  )
}

export function Privacy() {
  return (
    <Page title="Privacy policy">
      <p>This is a hackathon prototype built for Agentika 2.0. We collect only what the service needs to work:</p>
      <ul className="list-disc space-y-1 pl-5">
        <li>Your email, name and a hashed password.</li>
        <li>Your WhatsApp identifier, after you link it by sending us a code.</li>
        <li>An Instagram access token (encrypted) so we can publish posts you approve.</li>
        <li>Videos you send us, the edited versions, transcripts, captions and an activity log.</li>
      </ul>
      <p>
        Videos are processed on our server. Short excerpts (still frames and transcript text) are sent to Anthropic's Claude API to plan
        edits and write captions. We do not sell data or use it for advertising.
      </p>
      <p>
        The WhatsApp bot ignores and does not store messages from people who have not linked an account. You can delete your data at any
        time: see <Link to="/data-deletion" className="font-semibold text-brand-600">data deletion</Link>.
      </p>
    </Page>
  )
}

export function Terms() {
  return (
    <Page title="Terms">
      <p>This prototype is provided as-is for demonstration. You are responsible for the content you publish and must own the rights to it.</p>
      <p>Nothing is posted to Instagram without your explicit approval of the edit, the caption and the posting time.</p>
    </Page>
  )
}

export function DataDeletion() {
  return (
    <Page title="Data deletion">
      <p>To delete your data:</p>
      <ol className="list-decimal space-y-1 pl-5">
        <li>Disconnect Instagram and WhatsApp from the onboarding page, or remove the app in Instagram → Settings → Apps and websites.</li>
        <li>Email the team from the address on your account and ask for deletion. We delete your account, videos, captions and logs within 7 days.</li>
      </ol>
    </Page>
  )
}
