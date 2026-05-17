'use client';

import { ChatView } from '@/src/components/chat/ChatView';

// Default view — the chat interface. Rendered inside the `(app)` route
// group layout (`AppChrome`), which supplies the sidebar/header chrome,
// the auth gate, and the shared `/ws` connection.
export default function ChatPage() {
  return <ChatView />;
}
