import Foundation
import Network
import TreeCore

@MainActor
final class BonjourDeviceDiscovery {
    enum State: Sendable {
        case ready
        case waiting(String)
        case failed(String)
    }

    private let queue = DispatchQueue(label: "run.kan.treewatering.bonjour")
    private var browser: NWBrowser?
    private var generation = 0
    private var seenNames = Set<String>()
    private var candidateHandler: ((BonjourDeviceCandidate) -> Void)?
    private var stateHandler: ((State) -> Void)?

    func start(
        onCandidate: @escaping (BonjourDeviceCandidate) -> Void,
        onState: @escaping (State) -> Void
    ) {
        stop()
        generation += 1
        let currentGeneration = generation
        seenNames.removeAll()
        candidateHandler = onCandidate
        stateHandler = onState

        let parameters = NWParameters.tcp
        parameters.includePeerToPeer = false
        let browser = NWBrowser(
            for: .bonjour(type: BonjourDeviceCandidate.serviceType, domain: "local."),
            using: parameters
        )
        self.browser = browser

        browser.stateUpdateHandler = { [weak self] state in
            let mappedState: State?
            switch state {
            case .ready:
                mappedState = .ready
            case let .waiting(error):
                mappedState = .waiting(error.localizedDescription)
            case let .failed(error):
                mappedState = .failed(error.localizedDescription)
            default:
                mappedState = nil
            }
            guard let mappedState else { return }
            Task { @MainActor [weak self] in
                guard let self, generation == currentGeneration else { return }
                stateHandler?(mappedState)
            }
        }

        browser.browseResultsChangedHandler = { [weak self] results, _ in
            let names = results.compactMap { result -> String? in
                guard case let .service(name, _, _, _) = result.endpoint else {
                    return nil
                }
                return name
            }
            Task { @MainActor [weak self] in
                guard let self, generation == currentGeneration else { return }
                accept(names: names)
            }
        }
        browser.start(queue: queue)
    }

    func stop() {
        generation += 1
        browser?.cancel()
        browser = nil
        seenNames.removeAll()
        candidateHandler = nil
        stateHandler = nil
    }

    private func accept(names: [String]) {
        for name in names.sorted() where seenNames.insert(name).inserted {
            guard let candidate = BonjourDeviceCandidate(serviceName: name) else {
                continue
            }
            candidateHandler?(candidate)
        }
    }
}
