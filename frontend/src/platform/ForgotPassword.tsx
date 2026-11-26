import type { ReactNode } from 'react'
import { ForgotPassword } from '../tenant/StaffAuth'
import { AuthLayout } from '../ui/Auth'
import { useDocumentTitle } from '../ui/kit'
import { BackButton } from '../ui/BackButton'

function PlatformFrame({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  useDocumentTitle(title)
  return (
    <AuthLayout brand="NTS Restaurant Platform" logo="/logo-192.png" tagline="Reset the password of your platform administrator account with a code sent to your email."
      title={title} subtitle={subtitle} back={<BackButton to="/login">Back to sign in</BackButton>}>
      {children}
    </AuthLayout>
  )
}

/** Forgot password for the platform administrator: same secure code flow, in the platform's own layout. */
export default function PlatformForgotPassword() {
  return <ForgotPassword Frame={PlatformFrame} />
}
