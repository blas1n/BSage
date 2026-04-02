export function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="bg-surface-container-low border border-outline-variant/20 rounded-xl px-6 py-4">
        <div className="flex gap-1.5">
          <span className="w-2 h-2 bg-accent-light/60 rounded-full animate-bounce [animation-delay:0ms]" />
          <span className="w-2 h-2 bg-accent-light/60 rounded-full animate-bounce [animation-delay:150ms]" />
          <span className="w-2 h-2 bg-accent-light/60 rounded-full animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}
