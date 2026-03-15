import { app, BrowserWindow, ipcMain, dialog } from 'electron'
import path from 'path'
import { spawn, ChildProcess } from 'child_process'

let mainWindow: BrowserWindow | null = null
let pythonProcess: ChildProcess | null = null

const PYTHON_PORT = 8741
const isDev = !app.isPackaged

function startPythonBackend() {
  const srcDir = path.resolve(__dirname, '..', '..', 'src')
  pythonProcess = spawn('python', ['-m', 'uvicorn', 'api.server:app', '--port', String(PYTHON_PORT), '--host', '127.0.0.1'], {
    cwd: srcDir,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  pythonProcess.stdout?.on('data', (data: Buffer) => {
    console.log(`[Python] ${data.toString().trim()}`)
  })

  pythonProcess.stderr?.on('data', (data: Buffer) => {
    console.log(`[Python] ${data.toString().trim()}`)
  })

  pythonProcess.on('error', (err: Error) => {
    console.error('Failed to start Python backend:', err)
  })

  pythonProcess.on('exit', (code: number | null) => {
    console.log(`Python backend exited with code ${code}`)
    pythonProcess = null
  })
}

async function waitForBackend(maxRetries = 30, delayMs = 500): Promise<boolean> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const response = await fetch(`http://127.0.0.1:${PYTHON_PORT}/api/health`)
      if (response.ok) return true
    } catch {
      // Backend not ready yet
    }
    await new Promise(resolve => setTimeout(resolve, delayMs))
  }
  return false
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    title: 'Tournament Manager',
  })

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

// IPC handlers
ipcMain.handle('dialog:openFile', async (_event, filters: Electron.FileFilter[]) => {
  if (!mainWindow) return null
  const result = await dialog.showOpenDialog(mainWindow, {
    filters,
    properties: ['openFile'],
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('dialog:saveFile', async (_event, defaultPath: string, filters: Electron.FileFilter[]) => {
  if (!mainWindow) return null
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath,
    filters,
  })
  return result.canceled ? null : result.filePath
})

ipcMain.handle('print:html', async (_event, html: string) => {
  const printWin = new BrowserWindow({
    show: false,
    webPreferences: { contextIsolation: true },
  })
  await printWin.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
  printWin.webContents.print({}, (success) => {
    printWin.close()
    return success
  })
})

ipcMain.handle('print:pdf', async (_event, html: string, savePath: string) => {
  const printWin = new BrowserWindow({
    show: false,
    webPreferences: { contextIsolation: true },
  })
  await printWin.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
  const pdfData = await printWin.webContents.printToPDF({
    pageSize: 'A4',
    printBackground: true,
  })
  const fs = await import('fs')
  fs.writeFileSync(savePath, pdfData)
  printWin.close()
  return savePath
})

app.whenReady().then(async () => {
  startPythonBackend()
  const backendReady = await waitForBackend()
  if (!backendReady) {
    console.error('Python backend failed to start')
  }
  createWindow()
})

app.on('window-all-closed', () => {
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
  app.quit()
})

app.on('before-quit', () => {
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
})
