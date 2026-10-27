// A template (not a layout) remounts on every navigation, so each page fades in.
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="view-enter">{children}</div>;
}
