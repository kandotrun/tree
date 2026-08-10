public struct StatusAdoptionGate: Sendable {
    public struct Token: Equatable, Sendable {
        fileprivate let revision: UInt
    }

    private var revision: UInt = 0
    private var activeOperationCount = 0

    public init() {}

    public func beginStatusRequest() -> Token? {
        guard activeOperationCount == 0 else { return nil }
        return Token(revision: revision)
    }

    public mutating func beginOperation() {
        activeOperationCount += 1
        revision &+= 1
    }

    public mutating func endOperation() {
        assert(activeOperationCount > 0)
        if activeOperationCount > 0 {
            activeOperationCount -= 1
        }
        revision &+= 1
    }

    public func canAdopt(_ token: Token) -> Bool {
        activeOperationCount == 0 && token.revision == revision
    }
}
