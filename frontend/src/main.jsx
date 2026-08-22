import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './App.css'
import { installAccessCodeInterceptors } from './accessCode'

// Must run before any component issues a request, so every call carries the code.
installAccessCodeInterceptors()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
