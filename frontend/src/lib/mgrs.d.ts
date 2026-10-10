declare module 'mgrs' {
  export function forward(lonlat: [number, number], accuracy?: number): string
  export function toPoint(mgrs: string): [number, number]
}
