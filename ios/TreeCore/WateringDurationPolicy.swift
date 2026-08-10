public enum WateringDurationPolicy {
    private static let presets = [5, 10, 30, 60, 120]
    private static let absoluteMaximumSeconds = 180

    public static func options(
        maximumSeconds: Int,
        including currentSeconds: Int? = nil
    ) -> [Int] {
        let maximum = min(maximumSeconds, absoluteMaximumSeconds)
        guard maximum >= 1 else { return [] }
        var available = presets.filter { $0 <= maximum }
        if available.isEmpty {
            available = [maximum]
        }
        if let currentSeconds,
           (1 ... maximum).contains(currentSeconds),
           !available.contains(currentSeconds) {
            available.append(currentSeconds)
            available.sort()
        }
        return available
    }

    public static func normalized(
        currentSeconds: Int,
        maximumSeconds: Int
    ) -> Int? {
        let available = options(
            maximumSeconds: maximumSeconds,
            including: currentSeconds
        )
        guard let first = available.first else { return nil }
        if available.contains(currentSeconds) {
            return currentSeconds
        }
        return available.last(where: { $0 <= currentSeconds }) ?? first
    }
}
