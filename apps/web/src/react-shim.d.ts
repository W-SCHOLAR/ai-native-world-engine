declare module "react" {
  export type ReactNode = unknown;
  export type FormEvent<T = Element> = {
    currentTarget: T;
    target: EventTarget;
    preventDefault(): void;
  };

  export function useEffect(effect: () => void | (() => void), deps?: unknown[]): void;

  export function useMemo<T>(factory: () => T, deps: unknown[]): T;

  export function useCallback<T extends (...args: any[]) => any>(callback: T, deps: unknown[]): T;

  export function useRef<T>(initialValue: T): { current: T };

  export function useState<T>(
    initialValue: T | (() => T)
  ): [T, (value: T | ((previous: T) => T)) => void];

  export function lazy<T>(factory: () => Promise<{ default: T }>): T;

  export function memo<P>(
    component: (props: P) => unknown,
    compare?: (previous: Readonly<P>, next: Readonly<P>) => boolean,
  ): (props: P) => unknown;

  export const Suspense: (props: { children?: ReactNode; fallback?: ReactNode }) => unknown;

  const React: {
    StrictMode: (props: { children?: ReactNode }) => unknown;
  };

  export default React;
}

declare module "react-dom/client" {
  export function createRoot(element: HTMLElement): {
    render(children: unknown): void;
  };
}

declare module "react/jsx-runtime" {
  export const jsx: unknown;
  export const jsxs: unknown;
  export const Fragment: unknown;
}

declare namespace JSX {
  interface IntrinsicElements {
    [elementName: string]: any;
  }
}
