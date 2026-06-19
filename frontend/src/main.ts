import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './assets/index.css'
import { useTheme } from './composables/useTheme'

useTheme().initTheme()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
