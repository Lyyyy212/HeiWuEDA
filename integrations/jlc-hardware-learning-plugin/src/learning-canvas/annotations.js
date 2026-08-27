import { shapeForAnnotationCommand } from './model.js'

const ALLOWED_KINDS = new Set(['note', 'highlight', 'rectangle', 'arrow'])

export function hasAppliedCommand(snapshot, command) {
  return Object.values(snapshot?.store ?? {}).some((shape) =>
    shape?.typeName === 'shape' &&
    shape.meta?.hardwareLearningOperationId === command.operationId &&
    shape.meta?.hardwareLearningCommandId === command.commandId
  )
}

export function applyLearningAnnotationOperations(snapshot, pageId, operations = []) {
  let next = structuredClone(snapshot)
  const appliedCommands = []
  for (const operation of operations) {
    for (const command of operation.commands ?? []) {
      if (!ALLOWED_KINDS.has(command.kind)) {
        throw new Error(`不允许的学习标注：${command.kind}`)
      }
      if (command.pageId !== pageId || operation.pageId !== pageId) {
        throw new Error(`学习标注页不匹配：${command.pageId || operation.pageId}`)
      }
      if (hasAppliedCommand(next, command)) continue
      const shape = shapeForAnnotationCommand(next, command)
      next.store[shape.id] = shape
      appliedCommands.push(command.commandId)
    }
  }
  return {
    snapshot: appliedCommands.length ? next : snapshot,
    changed: appliedCommands.length > 0,
    appliedCommands
  }
}
