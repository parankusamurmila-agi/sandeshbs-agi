interface Props {
  /** Optional label shown beside the spinner, e.g. for full-page loads. */
  label?: string;
}

/** Centered spinner used for page-level loading states. */
export default function Spinner({ label }: Props) {
  return (
    <div className="page-loader">
      <span className="spinner spinner-accent" aria-hidden="true" />
      {label && <span>{label}</span>}
    </div>
  );
}
