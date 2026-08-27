import React from 'react'
import { createRoot } from 'react-dom/client'
import HardwareLearningCanvas from './learning-canvas/HardwareLearningCanvas.jsx'
import './styles.css'

function mountHardwareLearning() {
  createRoot(document.getElementById('root')).render(<HardwareLearningCanvas />)
}

mountHardwareLearning()
