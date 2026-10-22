import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import Generate from "./views/Generate.vue";
import Library from "./views/Library.vue";
import Logs from "./views/Logs.vue";
import Settings from "./views/Settings.vue";
import "./styles/tokens.css";
import "./styles/studio.css";
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: Generate },
    { path: "/library", component: Library },
    { path: "/logs", component: Logs },
    { path: "/settings", component: Settings },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
createApp(App).use(createPinia()).use(router).mount("#app");
