// Global type augmentations

declare global {
  interface Window {
    _mc_timer?: ReturnType<typeof setTimeout>;
  }
}

export {};
