import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('NETRA UI Caught Error:', error, errorInfo)
    this.setState({ errorInfo })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '40px',
          background: '#090d16',
          color: '#e2e8f4',
          fontFamily: 'system-ui, sans-serif',
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <div style={{
            maxWidth: '680px',
            width: '100%',
            background: '#0f172a',
            border: '1px solid #ef4444',
            borderRadius: '8px',
            padding: '24px',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)'
          }}>
            <h2 style={{ color: '#ef4444', marginBottom: '12px', fontSize: '18px' }}>
              NETRA UI Error — Render Exception Caught
            </h2>
            <p style={{ color: '#94a3b8', fontSize: '13px', marginBottom: '16px' }}>
              A component crashed during rendering. Full details below:
            </p>
            <pre style={{
              background: '#020617',
              color: '#f87171',
              padding: '12px',
              borderRadius: '6px',
              overflowX: 'auto',
              fontSize: '12px',
              marginBottom: '16px'
            }}>
              {this.state.error?.toString()}
              {'\n'}
              {this.state.errorInfo?.componentStack}
            </pre>
            <button
              onClick={() => window.location.reload()}
              style={{
                background: '#06b6d4',
                color: '#090d16',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '6px',
                fontWeight: 600,
                cursor: 'pointer'
              }}
            >
              Reload Dashboard
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
