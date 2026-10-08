import type { ButtonHTMLAttributes, ReactNode } from "react";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** When true, show an inline spinner and disable the button. */
  loading?: boolean;
  children: ReactNode;
}

/**
 * A <button> that renders a spinner (and disables itself) while `loading`,
 * so any action the user has to wait on reads as "working" rather than frozen.
 */
export default function Button({ loading = false, disabled, children, className, ...rest }: Props) {
  return (
    <button className={className} disabled={disabled || loading} aria-busy={loading} {...rest}>
      {loading && <span className="spinner" aria-hidden="true" />}
      <span>{children}</span>
    </button>
  );
}
