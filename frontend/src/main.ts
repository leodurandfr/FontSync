import { createApp } from "vue";
import { createPinia } from "pinia";
import router from "./router";
import App from "./App.vue";
import "./assets/index.css";
import { useTheme } from "./composables/useTheme";
import { i18n, readStoredLocale } from "./i18n";

useTheme().initTheme();
document.documentElement.setAttribute("lang", readStoredLocale());

const app = createApp(App);
app.use(createPinia());
app.use(i18n);
app.use(router);
app.mount("#app");
