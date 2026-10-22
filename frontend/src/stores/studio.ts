import type { TaskRequest } from "../api";
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { api, send, active, ApiError, type Task } from "../api";
export const useStudio = defineStore("studio", () => {
  const bootstrap = ref<any>(null),
    task = ref<Task | null>(null),
    notice = ref(""),
    error = ref(""),
    connected = ref(true),
    ready = ref(false);
  const progressVisible = ref(false),
    lastTask = ref<Task | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined,
    hide: ReturnType<typeof setTimeout> | undefined,
    stopped = false;
  const busy = computed(() => active(task.value));
  function fail(e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  }
  async function refreshBootstrap() {
    bootstrap.value = await api("/bootstrap");
  }
  async function initialize() {
    try {
      await refreshBootstrap();
      task.value = bootstrap.value.current_task;
      progressVisible.value = active(task.value);
      ready.value = true;
      schedule();
    } catch (e) {
      fail(e);
      connected.value = false;
      schedule(true);
    }
  }
  function schedule(retry = false) {
    clearTimeout(timer);
    if (!stopped && (busy.value || retry)) timer = setTimeout(poll, 2000);
  }
  async function poll() {
    try {
      const previous = task.value;
      task.value =
        previous && active(previous)
          ? await api("/tasks/" + previous.id)
          : await api("/tasks/current");
      if (active(task.value) && (!previous || task.value?.id !== previous.id))
        progressVisible.value = true;
      connected.value = true;
      if (previous && active(previous) && task.value && !active(task.value)) {
        lastTask.value = task.value;
        clearTimeout(hide);
        hide = setTimeout(
          () => (progressVisible.value = false),
          task.value.status === "succeeded" ? 6000 : 12000,
        );
        if (task.value.error) error.value = task.value.error;
      }
      if (!ready.value) {
        await refreshBootstrap();
        ready.value = true;
      }
      schedule();
    } catch {
      connected.value = false;
      schedule(true);
    }
  }
  let pendingRequest: { fingerprint: string; id: string } | null = null;
  async function start(
    body: Pick<TaskRequest, "generation"> &
      Partial<Omit<TaskRequest, "generation" | "request_id">>,
  ) {
    error.value = "";
    const fingerprint = JSON.stringify(body);
    if (pendingRequest?.fingerprint !== fingerprint)
      pendingRequest = { fingerprint, id: crypto.randomUUID() };
    let value: Task;
    try {
      value = await send<Task>("/tasks", {
        request_id: pendingRequest!.id,
        ...body,
      });
      pendingRequest = null;
    } catch (e) {
      if (e instanceof ApiError) pendingRequest = null;
      else {
        connected.value = false;
        schedule(true);
      }
      throw e;
    }
    task.value = value;
    lastTask.value = value;
    progressVisible.value = true;
    clearTimeout(hide);
    schedule();
    return value;
  }
  async function stop() {
    if (task.value) {
      task.value = await send("/tasks/" + task.value.id + "/stop", {});
      lastTask.value = task.value;
      clearTimeout(hide);
      hide = setTimeout(() => (progressVisible.value = false), 12000);
      schedule();
    }
  }
  function dispose() {
    stopped = true;
    clearTimeout(timer);
    clearTimeout(hide);
  }
  return {
    bootstrap,
    task,
    lastTask,
    notice,
    error,
    connected,
    ready,
    progressVisible,
    busy,
    fail,
    initialize,
    refreshBootstrap,
    start,
    stop,
    dispose,
  };
});
