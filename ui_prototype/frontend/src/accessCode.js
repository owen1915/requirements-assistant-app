import axios from 'axios'

// The shared access code the operator hands out. Kept in sessionStorage so it
// survives navigation and refreshes but not a closed tab, and attached to every
// API request by the interceptor below.

const STORAGE_KEY = 'incose_access_code'

export function getAccessCode() {
  try {
    return sessionStorage.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function setAccessCode(code) {
  try {
    sessionStorage.setItem(STORAGE_KEY, code)
  } catch {
    /* private browsing — the code just won't persist across refreshes */
  }
}

export function clearAccessCode() {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* nothing to clean up */
  }
}

// Listeners fire when the server rejects the stored code, so the app can send
// the user back to the gate instead of showing a broken page.
const rejectionListeners = new Set()

export function onAccessRejected(fn) {
  rejectionListeners.add(fn)
  return () => rejectionListeners.delete(fn)
}

export function installAccessCodeInterceptors() {
  axios.interceptors.request.use((config) => {
    const code = getAccessCode()
    if (code) {
      config.headers = { ...config.headers, 'X-Access-Code': code }
    }
    return config
  })

  axios.interceptors.response.use(
    (response) => response,
    (error) => {
      // A stored code that stopped working (rotated, or never valid) should
      // not leave the user stuck retrying with it.
      if (error.response?.status === 401) {
        clearAccessCode()
        rejectionListeners.forEach((fn) => fn())
      }
      return Promise.reject(error)
    },
  )
}
