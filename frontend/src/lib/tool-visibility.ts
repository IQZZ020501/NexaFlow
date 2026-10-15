/** Capabilities configured outside the regular Tool catalogs. */
export function isRegularTool(functionName: string) {
  return (
    functionName !== "generate_image" &&
    functionName !== "bash" &&
    functionName !== "install_skill_dependencies"
  )
}
