<script setup lang="ts">
import { ref, onMounted } from "vue";
import GlassCard from "../components/GlassCard.vue";
import Field from "../components/Field.vue";
import VoiceProfiles from "../components/VoiceProfiles.vue";
import { api, send, upload } from "../api";
import { useStudio } from "../stores/studio";
const store = useStudio(),
  password = ref(""),
  logged = ref(false),
  configs = ref<any>({}),
  forms = ref<Record<string, any>>({}),
  oldPassword = ref(""),
  newPassword = ref(""),
  confirmPassword = ref(""),
  voiceText = ref(""),
  voiceProvider = ref(""),
  voiceLanguage = ref(""),
  catalog = ref<any[]>([]),
  voiceFile = ref(""),
  voiceResult = ref<any>(null),
  visibleKeys = ref<Record<string, boolean>>({});
const labels: Record<string, string> = {
  openai: "MiMo",
  minimax: "MiniMax",
  qwen: "Qwen TTS",
  deepseek: "DeepSeek · 角色拆分",
};
async function refresh() {
  configs.value = await api("/settings");
  forms.value = Object.fromEntries(
    Object.entries(configs.value).map(([key, c]: [string, any]) => [
      key,
      {
        api_key: "",
        base_url: c.base_url || "",
        model: c.model || "",
        clear_key: false,
      },
    ]),
  );
  catalog.value = await api("/voices");
}
async function login() {
  try {
    await send("/admin/login", { password: password.value });
    password.value = "";
    logged.value = true;
  } catch (e) {
    store.fail(e);
  }
}
async function logout() {
  await send("/admin/logout", {});
  logged.value = false;
  await refresh();
}
async function save(key: string) {
  try {
    configs.value[key] = await send(
      "/settings/" + key,
      forms.value[key],
      "PUT",
    );
    forms.value[key].api_key = "";
    store.notice = "配置已保存。";
  } catch (e) {
    store.fail(e);
  }
}
async function test(key: string) {
  try {
    const result = await send("/settings/" + key + "/test", forms.value[key]);
    store.notice = result.message;
  } catch (e) {
    store.fail(e);
  }
}
async function reveal(key: string) {
  try {
    forms.value[key].api_key = (await api("/settings/" + key)).api_key;
  } catch (e) {
    store.fail(e);
  }
}
async function changePassword() {
  try {
    if (newPassword.value !== confirmPassword.value)
      throw new Error("两次新密码不一致。");
    await send("/admin/password", {
      old_password: oldPassword.value,
      new_password: newPassword.value,
    });
    logged.value = false;
    oldPassword.value = newPassword.value = confirmPassword.value = "";
    store.notice = "密码已修改，请重新登录。";
  } catch (e) {
    store.fail(e);
  }
}
async function attach(e: Event) {
  try {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (f) voiceFile.value = (await upload(f)).id;
  } catch (e) {
    store.fail(e);
  }
}
async function importVoices() {
  voiceResult.value = null;
  store.error = "";
  try {
    const result = await send<any>("/voices/import", {
      file_id: voiceFile.value || null,
      text: voiceFile.value ? "" : voiceText.value,
      provider: voiceProvider.value || null,
      language: voiceLanguage.value,
    });
    voiceResult.value = result;
    await refresh();
    await store.refreshBootstrap();
    store.notice = `已导入 ${result.count} 个音色。`;
  } catch (e) {
    store.fail(e);
  }
}
async function clearVoices() {
  try {
    await api("/voices", { method: "DELETE" });
    voiceResult.value = null;
    await refresh();
    await store.refreshBootstrap();
  } catch (e) {
    store.fail(e);
  }
}
onMounted(() => refresh().catch(store.fail));
</script>
<template>
  <div class="page-view">
    <div class="hero">
      <h1>工作台设置</h1>
      <p>管理语音服务、角色分析与音色目录。</p>
    </div>
    <GlassCard
      v-if="!logged"
      title="管理员登录"
      description="登录后可查看与修改 API 配置。"
      ><form @submit.prevent="login">
        <Field label="管理员密码" type="password" v-model="password" /><button
          class="primary section-space"
          type="submit"
        >
          登录
        </button>
      </form></GlassCard
    ><template v-else
      ><div class="toolbar section-space">
        <span class="muted">管理员会话已建立</span
        ><span class="spacer" /><button @click="logout">退出登录</button>
      </div>
      <GlassCard v-for="(form, key) in forms" :key="key" :title="labels[key]"
        ><div class="fields-grid">
          <Field
            label="API Key（留空保留）"
            :type="visibleKeys[key] ? 'text' : 'password'"
            v-model="form.api_key"
            :hint="configs[key].masked_key || '尚未配置'"
          /><Field
            v-if="key !== 'minimax'"
            label="Base URL"
            v-model="form.base_url"
          /><Field
            v-if="key === 'qwen' || key === 'deepseek'"
            label="模型"
            v-model="form.model"
          /><Field
            label="清除已保存密钥"
            type="checkbox"
            v-model="form.clear_key"
          />
        </div>
        <div class="toolbar section-space">
          <button @click="reveal(String(key))">读取已保存密钥</button
          ><button @click="visibleKeys[key] = !visibleKeys[key]">
            {{ visibleKeys[key] ? "隐藏密钥" : "显示密钥" }}</button
          ><button @click="test(String(key))">测试连接</button
          ><button class="primary" @click="save(String(key))">保存配置</button>
        </div></GlassCard
      ><GlassCard title="修改管理员密码"
        ><div class="fields-grid">
          <Field label="原密码" type="password" v-model="oldPassword" /><Field
            label="新密码（至少 4 位）"
            type="password"
            v-model="newPassword"
          /><Field
            label="确认新密码"
            type="password"
            v-model="confirmPassword"
          />
        </div>
        <button class="section-space" @click="changePassword">
          修改密码
        </button></GlassCard
      ></template
    ><VoiceProfiles /><GlassCard
      title="人工音色目录"
      description="导入官网音色说明，让新增音色出现在声音选择与角色工作台。"
      ><div class="fields-grid">
        <Field
          label="提供商"
          v-model="voiceProvider"
          :options="[
            { value: '', label: '自动识别' },
            { value: 'openai', label: 'MiMo' },
            { value: 'minimax', label: 'MiniMax' },
          ]"
        /><Field
          label="默认语言"
          v-model="voiceLanguage"
          :options="[
            { value: '', label: '自动识别' },
            { value: 'zh', label: '中文' },
            { value: 'en', label: '英语' },
            { value: 'yue', label: '粤语' },
          ]"
        />
      </div>
      <Field
        class="section-space"
        label="粘贴音色说明"
        type="textarea"
        v-model="voiceText"
      /><label class="field section-space"
        ><span>或上传说明文件</span
        ><input
          type="file"
          accept=".json,.txt,.csv,.tsv,.md,.html,.htm,.docx,.pdf"
          @change="attach"
        /><small v-if="voiceFile"
          >已上传说明文件，解析时优先使用文件。</small
        ></label
      >
      <button v-if="voiceFile" class="quiet" @click="voiceFile = ''">
        改用粘贴内容
      </button>
      <div class="toolbar section-space">
        <button :disabled="store.busy" @click="importVoices">
          解析并保存音色</button
        ><button class="danger" :disabled="store.busy" @click="clearVoices">
          清空用户音色目录
        </button>
      </div>
      <p class="muted section-space">
        当前目录共 {{ catalog.length }} 个音色（含内置）。
      </p>
      <div v-if="voiceResult" class="section-space" aria-live="polite">
        <p>
          本次导入 {{ voiceResult.count }} 个音色{{
            voiceResult.source_name ? ` · ${voiceResult.source_name}` : ""
          }}
        </p>
        <ul v-if="voiceResult.warnings?.length" class="warning">
          <li v-for="warning in voiceResult.warnings" :key="warning">
            {{ warning }}
          </li>
        </ul>
        <ul v-if="voiceResult.entries?.length">
          <li
            v-for="entry in voiceResult.entries"
            :key="`${entry.provider}:${entry.voice_id}`"
          >
            {{ entry.display_name || entry.voice_id }} · {{ entry.voice_id }} ·
            {{ labels[entry.provider] || entry.provider }} ·
            {{ entry.language || "未标注语言" }}
          </li>
        </ul>
      </div></GlassCard
    >
  </div>
</template>
