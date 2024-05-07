import { debounce } from "lodash";
export const kBounceInterval = 200;

export const restoreInputState = (id: string, value?: string) => {
  const el = document.getElementById(id) as HTMLInputElement;
  if (value) {
    el.value = value;
  } else {
    el.value = "";
  }
};

export const restoreSelectState = (id: string, value?: string) => {
  const el = document.getElementById(id) as HTMLSelectElement;
  if (value) {
    el.value = value;
  } else {
    el.value = "";
  }
};

export const whenChanged = (id: string, fn: (value: string) => void) => {
  const el = document.getElementById(id) as HTMLSelectElement;
  const handleEvent = (e: Event) => {
    if (e.target) {
      const index = el.selectedIndex;
      if (index) {
        const value = index > -1 ? el.options[index].value : el.value;
        fn(value);
      } else {
        fn(el.value);
      }
    }
  }
  el.addEventListener("change", handleEvent);
  el.addEventListener("keyup", debounce(handleEvent, kBounceInterval));
}

export const showEmptyPanel = (message: string, controlPanelId?: string, targetId?: string) => {
  if (controlPanelId) {
    setControlsVisible(controlPanelId, false);
  }

  const targetEl = targetId ? document.getElementById(targetId) : document.body;
  if (targetEl) {
    const existingEmptyPanel = targetEl.querySelector(".empty-panel");
    if (existingEmptyPanel) {
      existingEmptyPanel.remove();
    }

    const emptyPanelEl = document.createElement("DIV");
    emptyPanelEl.classList.add("empty-panel");

    const emptyMessageEl = document.createElement("DIV");
    emptyMessageEl.innerText = message;
    emptyPanelEl.appendChild(emptyMessageEl);

    targetEl.appendChild(emptyPanelEl);
  }
}

export function setControlsVisible(id: string, visible: boolean) {
  const controls = document.getElementById(id);
  if (visible) {
    controls?.classList.remove("hidden");
  } else {
    controls?.classList.add("hidden");
  }
}



