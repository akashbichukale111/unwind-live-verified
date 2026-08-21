export default function Home() {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "3rem", maxWidth: "42rem" }}>
      <h1>UNWIND</h1>
      <p>
        Cache invalidation for decisions &mdash; when a fact turns out false,
        everything it touched raises its hand, and the system computes what must
        now be un-sent, un-paid, or apologised for.
      </p>
      <p>
        <strong>NOT BUILT.</strong> This is an empty Next.js skeleton. Task 1
        delivers scaffolding and the corpus only; the operator surface &mdash;
        the load lines, the blast radius, the four regimes, the UNRESOLVED
        queue &mdash; is a later task. Nothing on this page is a rendering of
        real data, because there is nothing here to render.
      </p>
    </main>
  );
}
