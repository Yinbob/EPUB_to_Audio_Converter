import type { components } from "./generated/api";
export type GenerationRequest = components["schemas"]["Generation"];
export type TaskRequest = components["schemas"]["TaskRequest"];
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    ...init,
    headers: {
      ...(!(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init.headers,
    },
  });
  const body = await response.json();
  if (!response.ok)
    throw new ApiError(
      body.error?.code || "request_failed",
      body.error?.message || "请求失败，请稍后重试。",
      response.status,
    );
  return body;
}
export const send = <T = any>(path: string, body: unknown, method = "POST") =>
  api<T>(path, { method, body: JSON.stringify(body) });
export type FileRef = {
  id: string;
  name: string;
  size: number;
  category: string;
  cover_id?: string | null;
};
export async function upload(file: File): Promise<FileRef> {
  const data = new FormData();
  data.append("file", file);
  return api("/uploads", { method: "POST", body: data });
}
export const fileUrl = (file: FileRef | string, download = false) =>
  "/api/v1/files/" +
  (typeof file === "string" ? file : file.id) +
  (download ? "?download=true" : "");
export interface Task {
  id: string;
  kind: string;
  status: string;
  created_at: number;
  error: string;
  result: any;
  progress: any;
}
export const active = (task: Task | null) =>
  !!task && ["starting", "running", "stopping"].includes(task.status);
