// Messages of the backend (English) -> what the user sees (Arabic).
const ERROR_MESSAGES = [
  ["quran segments are never modified", "الآيات لا يمكن تعديلها"],
  ["the selected part changed", "تغيّر النص بعد التحديد، حدّد الجزء مرة أخرى"],
  ["the selected part is outside", "التحديد خارج النص"],
  ["select at least two rows", "حدّد صفين متجاورين على الأقل للدمج"],
  ["only rows that are next to each other", "لا يمكن دمج إلا الصفوف المتجاورة"],
  ["can't be unmerged anymore", "لا يمكن فك الدمج: تغيّرت أجزاء الصف بعد الدمج"],
  ["not a merged row", "هذا الصف ليس صفًا مدموجًا"],
  ["the llm", "ردّ المساعد غير صالح، حاول مرة أخرى"],
];

export function translateError(message) {
  const found = ERROR_MESSAGES.find(([english]) => message.includes(english));
  return found ? found[1] : message;
}

export async function postJson(url, body) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    throw new Error("تعذّر الوصول إلى الخادم");
  }

  if (!response.ok) {
    let detail = "حدث خطأ";
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch (error) {
      // the body is not json, keep the default message
    }
    throw new Error(translateError(detail));
  }
  return response.json();
}
