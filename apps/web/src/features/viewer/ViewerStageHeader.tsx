type ViewerStageHeaderProps = {
  sceneTitle: string;
  runtimeAuthority: "authoritative_engine" | "static_visual_demo" | "local_projection_fallback";
  onExitWorld?: () => void;
};

export function ViewerStageHeader({
  sceneTitle,
  runtimeAuthority,
  onExitWorld,
}: ViewerStageHeaderProps) {
  return (
    <header className="world-hud world-hud--stage" aria-label="世界导航">
      <div>
        <h1>{sceneTitle}</h1>
        <div className="runtime-authority-badge" data-authority={runtimeAuthority} aria-label="运行时来源">
          <i />
          <span>{runtimeAuthority === "authoritative_engine" ? "PYTHON ENGINE" : runtimeAuthority === "static_visual_demo" ? "STATIC VISUAL DEMO" : "LOCAL FALLBACK"}</span>
        </div>
        <div className="scene-mode-tabs" aria-label="世界场景">
          <button className="return-to-book" onClick={onExitWorld} type="button">退出世界</button>
        </div>
      </div>
    </header>
  );
}
