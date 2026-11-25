import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './lib/auth'
import { NotificationProvider } from './lib/live'
import { installTableRefresh } from './lib/tableRefresh'
import { ThemeProvider } from './lib/theme'
import { DialogProvider } from './ui/dialogs'
import { ErrorBoundary, ToastProvider } from './ui/kit'
import { TENANT_BASE } from './lib/config'
import './index.css'
import './app.css'
import './auth.css'

installTableRefresh()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <BrowserRouter basename={TENANT_BASE || undefined}>
        <ThemeProvider>
          <ToastProvider>
            <DialogProvider>
              <AuthProvider>
                <NotificationProvider>
                  <App />
                </NotificationProvider>
              </AuthProvider>
            </DialogProvider>
          </ToastProvider>
        </ThemeProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
)
