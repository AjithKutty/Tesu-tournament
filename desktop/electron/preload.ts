import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  openFile: (filters: Electron.FileFilter[]) =>
    ipcRenderer.invoke('dialog:openFile', filters),

  saveFile: (defaultPath: string, filters: Electron.FileFilter[]) =>
    ipcRenderer.invoke('dialog:saveFile', defaultPath, filters),

  printHtml: (html: string) =>
    ipcRenderer.invoke('print:html', html),

  printPdf: (html: string, savePath: string) =>
    ipcRenderer.invoke('print:pdf', html, savePath),
})
