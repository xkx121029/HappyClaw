export function MobileSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, index) => (
        <div className="m-skel-row" key={index}>
          <div
            className="m-skel"
            style={{ width: 36, height: 36, borderRadius: 12 }}
          />
          <div style={{ flex: 1 }}>
            <div
              className="m-skel"
              style={{ width: "52%", height: 14, borderRadius: 6 }}
            />
            <div
              className="m-skel"
              style={{
                width: "78%",
                height: 11,
                borderRadius: 6,
                marginTop: 8,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
