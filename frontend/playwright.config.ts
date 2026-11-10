import {defineConfig} from '@playwright/test'

export default defineConfig({
  testDir:'./e2e',workers:1,timeout:45000,fullyParallel:false,
  use:{baseURL:'http://127.0.0.1:8001',viewport:{width:1440,height:1000},
    channel:process.env.AION_BROWSER||undefined,trace:'retain-on-failure'},
  webServer:{command:'python ../scripts/e2e_server.py',url:'http://127.0.0.1:8001/health',
    reuseExistingServer:false,timeout:60000,gracefulShutdown:{signal:'SIGTERM',timeout:10000}},
})
