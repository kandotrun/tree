import Foundation
import Security

protocol FirmwareUpdateKeyStoring {
    func loadKey(deviceName: String) throws -> String?
    func saveKey(_ key: String, deviceName: String) throws
    func deleteKey(deviceName: String) throws
}

enum FirmwareUpdateKeyStoreError: Error {
    case invalidDeviceName
    case invalidKey
    case unexpectedStatus(OSStatus)
}

struct FirmwareUpdateKeyStore: FirmwareUpdateKeyStoring {
    private let service = "run.kan.treewatering.firmware-ota"

    func loadKey(deviceName: String) throws -> String? {
        let account = try normalizedAccount(deviceName)
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess,
              let data = result as? Data,
              let key = String(data: data, encoding: .utf8),
              Self.isValidKey(key) else {
            if status == errSecSuccess {
                throw FirmwareUpdateKeyStoreError.invalidKey
            }
            throw FirmwareUpdateKeyStoreError.unexpectedStatus(status)
        }
        return key
    }

    func saveKey(_ key: String, deviceName: String) throws {
        guard Self.isValidKey(key) else {
            throw FirmwareUpdateKeyStoreError.invalidKey
        }
        let account = try normalizedAccount(deviceName)
        let data = Data(key.utf8)
        let query = baseQuery(account: account)
        let attributes = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecSuccess {
            return
        }
        guard updateStatus == errSecItemNotFound else {
            throw FirmwareUpdateKeyStoreError.unexpectedStatus(updateStatus)
        }

        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let addStatus = SecItemAdd(item as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw FirmwareUpdateKeyStoreError.unexpectedStatus(addStatus)
        }
    }

    func deleteKey(deviceName: String) throws {
        let account = try normalizedAccount(deviceName)
        let status = SecItemDelete(baseQuery(account: account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw FirmwareUpdateKeyStoreError.unexpectedStatus(status)
        }
    }

    private func baseQuery(account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    private func normalizedAccount(_ deviceName: String) throws -> String {
        let normalized = deviceName.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalized.isEmpty, normalized.utf8.count <= 64 else {
            throw FirmwareUpdateKeyStoreError.invalidDeviceName
        }
        return normalized
    }

    private static func isValidKey(_ key: String) -> Bool {
        key.utf8.count == 64
            && key.utf8.allSatisfy { byte in
                (48 ... 57).contains(byte) || (97 ... 102).contains(byte)
            }
    }
}
