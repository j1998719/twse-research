"""對外連線共用的 TLS 設定:用 certifi(Mozilla 的根憑證清單)驗證。

不用系統預設的根憑證,是因為 macOS 的 /etc/ssl/cert.pem 太舊。證交所、
櫃買、集保的憑證鏈是

    網站 → TWCA SSL Certification Authority → TWCA CYBER Root CA
         →(交叉簽署)TWCA Global Root CA

系統的清單裡沒有 TWCA CYBER Root CA,只能一路驗到舊的 TWCA Global Root CA
—— 而那張根憑證沒有 Subject Key Identifier。Python 3.13 預設開啟
VERIFY_X509_STRICT,就以 "Missing Subject Key Identifier" 拒絕連線。
certifi 有 TWCA CYBER Root CA,鏈在它那裡就結束,嚴格模式照樣通過。

所以這裡**沒有放寬任何檢查**,只是換一份比較新的根憑證清單。
"""

from __future__ import annotations

import ssl

import certifi


#: 所有對外請求共用。不要另外建 context,不然會掉回系統那份舊清單
TLS = ssl.create_default_context(cafile=certifi.where())
