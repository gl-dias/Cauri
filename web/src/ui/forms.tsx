import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

const control =
  "h-11 w-full rounded-[14px] border border-white/15 bg-black/25 px-3.5 text-[14px] text-ink placeholder:text-subtle outline-none transition-colors focus:border-accent focus:bg-black/35 disabled:opacity-60";

const CHEVRON =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-opacity='0.7' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")";

export function Field({ label, hint, error, children, htmlFor }: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[13px] font-medium text-muted">
        {label}
      </label>
      {children}
      {error ? (
        <span role="alert" className="text-[12px] text-loss">
          {error}
        </span>
      ) : hint ? (
        <span className="text-[12px] text-subtle">{hint}</span>
      ) : null}
    </div>
  );
}

export function TextInput({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${control} ${className}`} {...rest} />;
}

export function SelectInput({ className = "", children, style, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`${control} appearance-none bg-[length:16px] bg-[right_12px_center] bg-no-repeat pr-9 ${className}`}
      style={{ backgroundImage: CHEVRON, ...style }}
      {...rest}
    >
      {children}
    </select>
  );
}

export function TextArea({ className = "", ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`${control} h-auto min-h-20 py-2.5 ${className}`} {...rest} />;
}

/** Pílulas de filtro (uma ativa por vez). */
export function FilterPills<T extends string>({ options, value, onChange, label }: {
  options: { key: T; label: string; color?: string }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 md:mx-0 md:flex-wrap md:px-0">
      {options.map((o) => {
        const active = o.key === value;
        return (
          <button
            key={o.key}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.key)}
            className={`flex h-10 shrink-0 items-center gap-2 rounded-full border px-4 text-[13px] font-medium transition-colors ${
              active ? "border-white bg-white text-on-light" : "glass-pill border-white/15 text-muted hover:text-ink"
            }`}
          >
            {o.color ? <span className="size-2 rounded-full" style={{ background: o.color }} /> : null}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
