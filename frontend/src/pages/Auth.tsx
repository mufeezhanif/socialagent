import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Me } from '../api'
import { Button, Card, Field, Input, Logo } from '../ui'

function AuthForm({ mode }: { mode: 'login' | 'signup' }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const me = await api<Me>(`/api/auth/${mode === 'login' ? 'login' : 'register'}`, {
        method: 'POST',
        json: mode === 'login' ? { email, password } : { email, password, name },
      })
      qc.setQueryData(['me'], me)
      const onboarded = me.instagram && me.whatsapp?.linked
      navigate(mode === 'signup' || !onboarded ? '/onboarding' : '/app')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-gradient-to-b from-brand-50 to-white px-4">
      <div className="w-full max-w-md">
        <Link to="/" className="mb-6 flex justify-center">
          <Logo />
        </Link>
        <Card className="p-7">
          <h1 className="text-xl font-bold">{mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
          <p className="mt-1 text-sm text-slate-500">
            {mode === 'login' ? 'Log in to your dashboard.' : 'Takes a minute. Then connect Instagram and WhatsApp.'}
          </p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            {mode === 'signup' && (
              <Field label="Name">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ayesha" />
              </Field>
            )}
            <Field label="Email">
              <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
            </Field>
            <Field label="Password" hint={mode === 'signup' ? 'At least 8 characters' : undefined}>
              <Input type="password" required minLength={mode === 'signup' ? 8 : 1} value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Button type="submit" loading={loading} className="w-full">
              {mode === 'login' ? 'Log in' : 'Create account'}
            </Button>
          </form>
          <p className="mt-5 text-center text-sm text-slate-500">
            {mode === 'login' ? (
              <>No account? <Link to="/signup" className="font-semibold text-brand-600">Sign up</Link></>
            ) : (
              <>Already have one? <Link to="/login" className="font-semibold text-brand-600">Log in</Link></>
            )}
          </p>
        </Card>
      </div>
    </div>
  )
}

export const Login = () => <AuthForm mode="login" />
export const Signup = () => <AuthForm mode="signup" />
