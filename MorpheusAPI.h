#pragma once

#include <string>
#include <vector>
#include <memory>
#include <cstring>
#include <intrin.h>
#include <windows.h>
#include <winhttp.h>
#include <wincrypt.h>
#include <iphlpapi.h>
#include <wbemidl.h>
#include <comdef.h>
#include <nlohmann/json.hpp>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "crypt32.lib")
#pragma comment(lib, "iphlpapi.lib")
#pragma comment(lib, "wbemuuid.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")

using json = nlohmann::json;

namespace MorpheusAPI {

    // Структура для хранения информации об ответе API
    struct APIResponse {
        bool success;
        std::string error;
        json data;
        int remaining_days;
        int remaining_hours;
    };

    class MorpheusClient {
    private:
        std::string base_url;
        std::string uuid_cache;
        
        // Генерация UUID на основе железа
        std::string GenerateHardwareUUID() {
            if (!uuid_cache.empty()) {
                return uuid_cache;
            }

            std::string hardware_string;
            
            // 1. CPU ID
            int cpuInfo[4] = { -1 };
            __cpuid(cpuInfo, 0x80000002);
            char cpuName[0x40] = { 0 };
            memcpy(cpuName, cpuInfo, sizeof(cpuInfo));
            __cpuid(cpuInfo, 0x80000003);
            memcpy(cpuName + 16, cpuInfo, sizeof(cpuInfo));
            __cpuid(cpuInfo, 0x80000004);
            memcpy(cpuName + 32, cpuInfo, sizeof(cpuInfo));
            hardware_string += std::string(cpuName, 48);
            
            // 2. CPU Serial Number (если доступен)
            int cpuInfo2[4] = { 0 };
            __cpuid(cpuInfo2, 1);
            hardware_string += std::to_string(cpuInfo2[0]) + std::to_string(cpuInfo2[1]) + 
                              std::to_string(cpuInfo2[2]) + std::to_string(cpuInfo2[3]);
            
            // 3. Motherboard Serial Number (WMI)
            hardware_string += GetWMISerial("Win32_BaseBoard", "SerialNumber");
            
            // 4. BIOS Serial Number (WMI)
            hardware_string += GetWMISerial("Win32_BIOS", "SerialNumber");
            
            // 5. MAC Address первого сетевого адаптера
            hardware_string += GetMACAddress();
            
            // 6. Volume Serial Number системного диска
            hardware_string += GetVolumeSerial();
            
            // 7. Video Card ID (WMI)
            hardware_string += GetWMISerial("Win32_VideoController", "PNPDeviceID");
            
            // 8. RAM Serial Numbers (WMI)
            hardware_string += GetWMISerial("Win32_PhysicalMemory", "SerialNumber");
            
            // 9. Processor ID (WMI)
            hardware_string += GetWMISerial("Win32_Processor", "ProcessorId");
            
            // 10. Computer System UUID (WMI)
            hardware_string += GetWMISerial("Win32_ComputerSystemProduct", "UUID");
            
            // Хешируем полученную строку в MD5 и форматируем как UUID
            uuid_cache = HashToUUID(hardware_string);
            return uuid_cache;
        }
        
        // Получение серийного номера через WMI
        std::string GetWMISerial(const std::string& className, const std::string& property) {
            std::string result;
            HRESULT hres;
            
            // Инициализация COM
            hres = CoInitializeEx(0, COINIT_MULTITHREADED);
            if (FAILED(hres)) return "";
            
            // Инициализация безопасности COM
            hres = CoInitializeSecurity(NULL, -1, NULL, NULL, RPC_C_AUTHN_LEVEL_NONE,
                RPC_C_IMP_LEVEL_IMPERSONATE, NULL, EOAC_NONE, NULL);
            
            // Получение локатора WMI
            IWbemLocator* pLoc = NULL;
            hres = CoCreateInstance(CLSID_WbemLocator, 0, CLSCTX_INPROC_SERVER,
                IID_IWbemLocator, (LPVOID*)&pLoc);
            
            if (SUCCEEDED(hres)) {
                // Подключение к WMI
                IWbemServices* pSvc = NULL;
                hres = pLoc->ConnectServer(_bstr_t(L"ROOT\\CIMV2"), NULL, NULL, 0, NULL, 0, 0, &pSvc);
                
                if (SUCCEEDED(hres)) {
                    // Установка безопасности прокси
                    hres = CoSetProxyBlanket(pSvc, RPC_C_AUTHN_WINNT, RPC_C_AUTHZ_NONE, NULL,
                        RPC_C_AUTHN_LEVEL_CALL, RPC_C_IMP_LEVEL_IMPERSONATE, NULL, EOAC_NONE);
                    
                    if (SUCCEEDED(hres)) {
                        // Выполнение запроса WMI
                        std::wstring wQuery = L"SELECT " + std::wstring(property.begin(), property.end()) + 
                                             L" FROM " + std::wstring(className.begin(), className.end());
                        IEnumWbemClassObject* pEnumerator = NULL;
                        hres = pSvc->ExecQuery(bstr_t("WQL"), bstr_t(wQuery.c_str()),
                            WBEM_FLAG_FORWARD_ONLY | WBEM_FLAG_RETURN_IMMEDIATELY, NULL, &pEnumerator);
                        
                        if (SUCCEEDED(hres)) {
                            IWbemClassObject* pclsObj = NULL;
                            ULONG uReturn = 0;
                            
                            while (pEnumerator->Next(WBEM_INFINITE, 1, &pclsObj, &uReturn) == WBEM_S_NO_ERROR) {
                                VARIANT vtProp;
                                VariantInit(&vtProp);
                                
                                std::wstring wProperty = std::wstring(property.begin(), property.end());
                                hres = pclsObj->Get(wProperty.c_str(), 0, &vtProp, 0, 0);
                                
                                if (SUCCEEDED(hres) && vtProp.vt != VT_NULL && vtProp.vt != VT_EMPTY) {
                                    if (vtProp.vt == VT_BSTR) {
                                        std::wstring wstr(vtProp.bstrVal);
                                        result += std::string(wstr.begin(), wstr.end());
                                    }
                                }
                                
                                VariantClear(&vtProp);
                                pclsObj->Release();
                            }
                            
                            pEnumerator->Release();
                        }
                    }
                    pSvc->Release();
                }
                pLoc->Release();
            }
            
            CoUninitialize();
            return result;
        }
        
        // Получение MAC адреса первого сетевого адаптера
        std::string GetMACAddress() {
            std::string mac;
            IP_ADAPTER_INFO adapterInfo[16];
            DWORD dwBufLen = sizeof(adapterInfo);
            
            DWORD dwStatus = GetAdaptersInfo(adapterInfo, &dwBufLen);
            if (dwStatus == ERROR_SUCCESS) {
                PIP_ADAPTER_INFO pAdapterInfo = adapterInfo;
                if (pAdapterInfo) {
                    char macStr[18];
                    sprintf_s(macStr, "%02X-%02X-%02X-%02X-%02X-%02X",
                        pAdapterInfo->Address[0], pAdapterInfo->Address[1],
                        pAdapterInfo->Address[2], pAdapterInfo->Address[3],
                        pAdapterInfo->Address[4], pAdapterInfo->Address[5]);
                    mac = macStr;
                }
            }
            return mac;
        }
        
        // Получение серийного номера тома системного диска
        std::string GetVolumeSerial() {
            DWORD serialNumber = 0;
            if (GetVolumeInformationA("C:\\", NULL, 0, &serialNumber, NULL, NULL, NULL, 0)) {
                return std::to_string(serialNumber);
            }
            return "";
        }
        
        // Хеширование строки в MD5 и форматирование как UUID
        std::string HashToUUID(const std::string& input) {
            HCRYPTPROV hProv = 0;
            HCRYPTHASH hHash = 0;
            BYTE hash[16];
            DWORD hashLen = 16;
            
            if (!CryptAcquireContext(&hProv, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT)) {
                return "";
            }
            
            if (!CryptCreateHash(hProv, CALG_MD5, 0, 0, &hHash)) {
                CryptReleaseContext(hProv, 0);
                return "";
            }
            
            if (!CryptHashData(hHash, (BYTE*)input.c_str(), input.length(), 0)) {
                CryptDestroyHash(hHash);
                CryptReleaseContext(hProv, 0);
                return "";
            }
            
            if (!CryptGetHashParam(hHash, HP_HASHVAL, hash, &hashLen, 0)) {
                CryptDestroyHash(hHash);
                CryptReleaseContext(hProv, 0);
                return "";
            }
            
            CryptDestroyHash(hHash);
            CryptReleaseContext(hProv, 0);
            
            // Форматируем как UUID v4 (но используем MD5 хеш вместо случайных данных)
            char uuid[37];
            sprintf_s(uuid, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
                hash[0], hash[1], hash[2], hash[3],
                hash[4], hash[5],
                (hash[6] & 0x0F) | 0x40, hash[7],  // Версия 4
                (hash[8] & 0x3F) | 0x80, hash[9],  // Variant
                hash[10], hash[11], hash[12], hash[13], hash[14], hash[15]);
            
            return std::string(uuid);
        }
        
        // Выполнение HTTP запроса
        std::string HTTPRequest(const std::string& method, const std::string& endpoint, const json& body = json()) {
            std::string result;
            
            // Парсинг URL
            URL_COMPONENTSA urlComp;
            ZeroMemory(&urlComp, sizeof(urlComp));
            urlComp.dwStructSize = sizeof(urlComp);
            urlComp.dwSchemeLength = (DWORD)-1;
            urlComp.dwHostNameLength = (DWORD)-1;
            urlComp.dwUrlPathLength = (DWORD)-1;
            
            std::string fullUrl = base_url + endpoint;
            char urlBuffer[2048];
            strcpy_s(urlBuffer, fullUrl.c_str());
            
            if (!WinHttpCrackUrlA(urlBuffer, strlen(urlBuffer), 0, &urlComp)) {
                return "";
            }
            
            std::string host(urlComp.lpszHostName, urlComp.dwHostNameLength);
            std::string path(urlComp.lpszUrlPath, urlComp.dwUrlPathLength);
            
            // Открытие сессии WinHTTP
            HINTERNET hSession = WinHttpOpen(L"MorpheusAPI/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
            
            if (!hSession) {
                return "";
            }
            
            // Подключение к серверу
            INTERNET_PORT port = (urlComp.nPort == 0) ? 
                (urlComp.nScheme == INTERNET_SCHEME_HTTPS ? INTERNET_DEFAULT_HTTPS_PORT : INTERNET_DEFAULT_HTTP_PORT) :
                urlComp.nPort;
            HINTERNET hConnect = WinHttpConnectA(hSession, host.c_str(), port, 0);
            
            if (!hConnect) {
                WinHttpCloseHandle(hSession);
                return "";
            }
            
            // Открытие запроса
            const char* acceptTypes[] = { "application/json", NULL };
            HINTERNET hRequest = WinHttpOpenRequestA(hConnect, method.c_str(), path.c_str(),
                NULL, WINHTTP_NO_REFERER, acceptTypes,
                urlComp.nScheme == INTERNET_SCHEME_HTTPS ? WINHTTP_FLAG_SECURE : 0);
            
            if (!hRequest) {
                WinHttpCloseHandle(hConnect);
                WinHttpCloseHandle(hSession);
                return "";
            }
            
            // Добавление заголовков
            std::string headers = "Content-Type: application/json\r\n";
            WinHttpAddRequestHeadersA(hRequest, headers.c_str(), headers.length(), WINHTTP_ADDREQ_FLAG_ADD);
            
            // Подготовка тела запроса
            std::string requestBody;
            if (!body.is_null() && !body.empty()) {
                requestBody = body.dump();
            }
            
            // Отправка запроса
            DWORD bodyLength = static_cast<DWORD>(requestBody.length());
            BOOL bResults = WinHttpSendRequestA(hRequest, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                bodyLength > 0 ? (LPVOID)requestBody.c_str() : WINHTTP_NO_REQUEST_DATA, 
                bodyLength, bodyLength, 0);
            
            if (bResults) {
                bResults = WinHttpReceiveResponse(hRequest, NULL);
            }
            
            if (bResults) {
                // Чтение ответа
                DWORD dwSize = 0;
                DWORD dwDownloaded = 0;
                
                do {
                    dwSize = 0;
                    if (!WinHttpQueryDataAvailable(hRequest, &dwSize)) {
                        break;
                    }
                    
                    if (dwSize == 0) break;
                    
                    std::vector<char> buffer(dwSize + 1);
                    ZeroMemory(buffer.data(), dwSize + 1);
                    
                    if (WinHttpReadData(hRequest, buffer.data(), dwSize, &dwDownloaded)) {
                        result.append(buffer.data(), dwDownloaded);
                    } else {
                        break;
                    }
                } while (dwSize > 0);
            }
            
            // Закрытие дескрипторов
            WinHttpCloseHandle(hRequest);
            WinHttpCloseHandle(hConnect);
            WinHttpCloseHandle(hSession);
            
            return result;
        }
        
    public:
        MorpheusClient(const std::string& url) : base_url(url) {
            // Инициализация COM для WMI
            CoInitializeEx(0, COINIT_MULTITHREADED);
        }
        
        ~MorpheusClient() {
            CoUninitialize();
        }
        
        // Получение UUID (кэшируется после первого вызова)
        std::string GetUUID() {
            return GenerateHardwareUUID();
        }
        
        // Активация/авторизация ключа
        APIResponse Auth(const std::string& productSlug, const std::string& key) {
            APIResponse response;
            response.success = false;
            
            std::string uuid = GetUUID();
            
            json requestBody;
            requestBody["key"] = key;
            requestBody["uuid"] = uuid;
            
            std::string endpoint = "/api/" + productSlug + "/auth";
            std::string result = HTTPRequest("POST", endpoint, requestBody);
            
            if (result.empty()) {
                response.error = "Network error";
                return response;
            }
            
            try {
                json jsonResponse = json::parse(result);
                
                if (jsonResponse.contains("success") && jsonResponse["success"].get<bool>()) {
                    response.success = true;
                    response.data = jsonResponse;
                    
                    if (jsonResponse.contains("remaining")) {
                        auto remaining = jsonResponse["remaining"];
                        if (remaining.contains("days")) {
                            response.remaining_days = remaining["days"].get<int>();
                        }
                        if (remaining.contains("hours")) {
                            response.remaining_hours = remaining["hours"].get<int>();
                        }
                    }
                } else {
                    response.success = false;
                    if (jsonResponse.contains("error")) {
                        response.error = jsonResponse["error"].get<std::string>();
                    } else {
                        response.error = "Unknown error";
                    }
                }
            } catch (const json::exception& e) {
                response.error = "JSON parse error: " + std::string(e.what());
            }
            
            return response;
        }
    };
}

/*
 * Пример использования:
 * 
 * #include "MorpheusAPI.h"
 * #include <iostream>
 * 
 * int main() {
 *     // Создаем клиент с базовым URL вашего API
 *     MorpheusAPI::MorpheusClient client("https://your-server.com");
 *     
 *     // Получаем UUID (генерируется один раз и кэшируется)
 *     std::string uuid = client.GetUUID();
 *     std::cout << "Hardware UUID: " << uuid << std::endl;
 *     
 *     // Активация/авторизация ключа
 *     MorpheusAPI::APIResponse response = client.Auth("stalcraft-chams", "YOUR-KEY-HERE");
 *     
 *     if (response.success) {
 *         std::cout << "Authorization successful!" << std::endl;
 *         std::cout << "Remaining: " << response.remaining_days << " days, " 
 *                   << response.remaining_hours << " hours" << std::endl;
 *     } else {
 *         std::cout << "Authorization failed: " << response.error << std::endl;
 *     }
 *     
 *     return 0;
 * }
 */

