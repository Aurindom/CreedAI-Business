import React from 'react'

// Keeps a chat crash inside the chat, so the rest of the site keeps working.
class ChatErrorBoundary extends React.Component {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error) {
    console.error('Chat panel error', error)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="msc-crash" role="alert">
        <strong>The chat stopped working.</strong>
        <p>You can still browse and compare tools on this page.</p>
        <button type="button" onClick={() => this.setState({ failed: false })}>Try the chat again</button>
      </div>
    )
  }
}

export default ChatErrorBoundary
