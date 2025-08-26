/*
 * ATTENTION: An "eval-source-map" devtool has been used.
 * This devtool is neither made for production nor for readable output files.
 * It uses "eval()" calls to create a separate source file with attached SourceMaps in the browser devtools.
 * If you are trying to read the output file, select a different devtool (https://webpack.js.org/configuration/devtool/)
 * or disable the default devtool with "devtool: false".
 * If you are looking for production-ready output files, see mode: "production" (https://webpack.js.org/configuration/mode/).
 */
(() => {
var exports = {};
exports.id = "pages/_app";
exports.ids = ["pages/_app"];
exports.modules = {

/***/ "./src/contexts/FileContext.tsx":
/*!**************************************!*\
  !*** ./src/contexts/FileContext.tsx ***!
  \**************************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
eval("__webpack_require__.r(__webpack_exports__);\n/* harmony export */ __webpack_require__.d(__webpack_exports__, {\n/* harmony export */   FileContext: () => (/* binding */ FileContext),\n/* harmony export */   FileProvider: () => (/* binding */ FileProvider),\n/* harmony export */   useFileContext: () => (/* binding */ useFileContext)\n/* harmony export */ });\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react/jsx-dev-runtime */ \"react/jsx-dev-runtime\");\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__);\n/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! react */ \"react\");\n/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_1__);\n\n\n// 기본값 생성\nconst defaultState = {\n    checkedFiles: [],\n    setCheckedFiles: ()=>{}\n};\n// Context 생성\nconst FileContext = /*#__PURE__*/ (0,react__WEBPACK_IMPORTED_MODULE_1__.createContext)(defaultState);\n// Context 사용을 위한 Hook\nfunction useFileContext() {\n    const context = (0,react__WEBPACK_IMPORTED_MODULE_1__.useContext)(FileContext);\n    if (!context) {\n        throw new Error(\"useFileContext must be used within a FileProvider\");\n    }\n    return context;\n}\n// Provider 컴포넌트\nfunction FileProvider({ children }) {\n    const [checkedFiles, setCheckedFiles] = (0,react__WEBPACK_IMPORTED_MODULE_1__.useState)([]);\n    // 실제 값 제공\n    const value = {\n        checkedFiles,\n        setCheckedFiles\n    };\n    return /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(FileContext.Provider, {\n        value: value,\n        children: children\n    }, void 0, false, {\n        fileName: \"/home/jeonghs/workspace/nextitslm/frontend/src/contexts/FileContext.tsx\",\n        lineNumber: 38,\n        columnNumber: 5\n    }, this);\n}\n//# sourceURL=[module]\n//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiLi9zcmMvY29udGV4dHMvRmlsZUNvbnRleHQudHN4IiwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7O0FBQW1FO0FBUW5FLFNBQVM7QUFDVCxNQUFNSSxlQUFpQztJQUNyQ0MsY0FBYyxFQUFFO0lBQ2hCQyxpQkFBaUIsS0FBTztBQUMxQjtBQUVBLGFBQWE7QUFDTixNQUFNQyw0QkFBY04sb0RBQWFBLENBQW1CRyxjQUFjO0FBRXpFLHNCQUFzQjtBQUNmLFNBQVNJO0lBQ2QsTUFBTUMsVUFBVVAsaURBQVVBLENBQUNLO0lBQzNCLElBQUksQ0FBQ0UsU0FBUztRQUNaLE1BQU0sSUFBSUMsTUFBTTtJQUNsQjtJQUNBLE9BQU9EO0FBQ1Q7QUFFQSxnQkFBZ0I7QUFDVCxTQUFTRSxhQUFhLEVBQUVDLFFBQVEsRUFBaUM7SUFDdEUsTUFBTSxDQUFDUCxjQUFjQyxnQkFBZ0IsR0FBR0gsK0NBQVFBLENBQVcsRUFBRTtJQUU3RCxVQUFVO0lBQ1YsTUFBTVUsUUFBUTtRQUNaUjtRQUNBQztJQUNGO0lBRUEscUJBQ0UsOERBQUNDLFlBQVlPLFFBQVE7UUFBQ0QsT0FBT0E7a0JBQzFCRDs7Ozs7O0FBR1AiLCJzb3VyY2VzIjpbIndlYnBhY2s6Ly9jaGF0Ym90LWZyb250ZW5kLy4vc3JjL2NvbnRleHRzL0ZpbGVDb250ZXh0LnRzeD8xODFiIl0sInNvdXJjZXNDb250ZW50IjpbImltcG9ydCBSZWFjdCwgeyBjcmVhdGVDb250ZXh0LCB1c2VDb250ZXh0LCB1c2VTdGF0ZSB9IGZyb20gJ3JlYWN0JztcblxuLy8g7KCE7JetIOyDge2DnCDsnbjthLDtjpjsnbTsiqQg7KCV7J2YXG5pbnRlcmZhY2UgRmlsZUNvbnRleHRTdGF0ZSB7XG4gIGNoZWNrZWRGaWxlczogc3RyaW5nW107XG4gIHNldENoZWNrZWRGaWxlczogKGZpbGVzOiBzdHJpbmdbXSkgPT4gdm9pZDtcbn1cblxuLy8g6riw67O46rCSIOyDneyEsVxuY29uc3QgZGVmYXVsdFN0YXRlOiBGaWxlQ29udGV4dFN0YXRlID0ge1xuICBjaGVja2VkRmlsZXM6IFtdLFxuICBzZXRDaGVja2VkRmlsZXM6ICgpID0+IHt9XG59O1xuXG4vLyBDb250ZXh0IOyDneyEsVxuZXhwb3J0IGNvbnN0IEZpbGVDb250ZXh0ID0gY3JlYXRlQ29udGV4dDxGaWxlQ29udGV4dFN0YXRlPihkZWZhdWx0U3RhdGUpO1xuXG4vLyBDb250ZXh0IOyCrOyaqeydhCDsnITtlZwgSG9va1xuZXhwb3J0IGZ1bmN0aW9uIHVzZUZpbGVDb250ZXh0KCkge1xuICBjb25zdCBjb250ZXh0ID0gdXNlQ29udGV4dChGaWxlQ29udGV4dCk7XG4gIGlmICghY29udGV4dCkge1xuICAgIHRocm93IG5ldyBFcnJvcigndXNlRmlsZUNvbnRleHQgbXVzdCBiZSB1c2VkIHdpdGhpbiBhIEZpbGVQcm92aWRlcicpO1xuICB9XG4gIHJldHVybiBjb250ZXh0O1xufVxuXG4vLyBQcm92aWRlciDsu7Ttj6zrhIztirhcbmV4cG9ydCBmdW5jdGlvbiBGaWxlUHJvdmlkZXIoeyBjaGlsZHJlbiB9OiB7IGNoaWxkcmVuOiBSZWFjdC5SZWFjdE5vZGUgfSkge1xuICBjb25zdCBbY2hlY2tlZEZpbGVzLCBzZXRDaGVja2VkRmlsZXNdID0gdXNlU3RhdGU8c3RyaW5nW10+KFtdKTtcbiAgXG4gIC8vIOyLpOygnCDqsJIg7KCc6rO1XG4gIGNvbnN0IHZhbHVlID0ge1xuICAgIGNoZWNrZWRGaWxlcyxcbiAgICBzZXRDaGVja2VkRmlsZXNcbiAgfTtcblxuICByZXR1cm4gKFxuICAgIDxGaWxlQ29udGV4dC5Qcm92aWRlciB2YWx1ZT17dmFsdWV9PlxuICAgICAge2NoaWxkcmVufVxuICAgIDwvRmlsZUNvbnRleHQuUHJvdmlkZXI+XG4gICk7XG59XG5cbiJdLCJuYW1lcyI6WyJSZWFjdCIsImNyZWF0ZUNvbnRleHQiLCJ1c2VDb250ZXh0IiwidXNlU3RhdGUiLCJkZWZhdWx0U3RhdGUiLCJjaGVja2VkRmlsZXMiLCJzZXRDaGVja2VkRmlsZXMiLCJGaWxlQ29udGV4dCIsInVzZUZpbGVDb250ZXh0IiwiY29udGV4dCIsIkVycm9yIiwiRmlsZVByb3ZpZGVyIiwiY2hpbGRyZW4iLCJ2YWx1ZSIsIlByb3ZpZGVyIl0sInNvdXJjZVJvb3QiOiIifQ==\n//# sourceURL=webpack-internal:///./src/contexts/FileContext.tsx\n");

/***/ }),

/***/ "./src/pages/_app.tsx":
/*!****************************!*\
  !*** ./src/pages/_app.tsx ***!
  \****************************/
/***/ ((module, __webpack_exports__, __webpack_require__) => {

"use strict";
eval("__webpack_require__.a(module, async (__webpack_handle_async_dependencies__, __webpack_async_result__) => { try {\n__webpack_require__.r(__webpack_exports__);\n/* harmony export */ __webpack_require__.d(__webpack_exports__, {\n/* harmony export */   \"default\": () => (/* binding */ App)\n/* harmony export */ });\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react/jsx-dev-runtime */ \"react/jsx-dev-runtime\");\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__);\n/* harmony import */ var _styles_globals_css__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @/styles/globals.css */ \"./src/styles/globals.css\");\n/* harmony import */ var _styles_globals_css__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_styles_globals_css__WEBPACK_IMPORTED_MODULE_1__);\n/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! react */ \"react\");\n/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_2___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_2__);\n/* harmony import */ var _utils_mui_provider__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! ../utils/mui-provider */ \"./src/utils/mui-provider.tsx\");\nvar __webpack_async_dependencies__ = __webpack_handle_async_dependencies__([_utils_mui_provider__WEBPACK_IMPORTED_MODULE_3__]);\n_utils_mui_provider__WEBPACK_IMPORTED_MODULE_3__ = (__webpack_async_dependencies__.then ? (await __webpack_async_dependencies__)() : __webpack_async_dependencies__)[0];\n\n\n\n\nfunction App({ Component, pageProps }) {\n    return /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(react__WEBPACK_IMPORTED_MODULE_2__.Fragment, {\n        children: /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(_utils_mui_provider__WEBPACK_IMPORTED_MODULE_3__.AppProvider, {\n            children: /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(Component, {\n                ...pageProps\n            }, void 0, false, {\n                fileName: \"/home/jeonghs/workspace/nextitslm/frontend/src/pages/_app.tsx\",\n                lineNumber: 10,\n                columnNumber: 9\n            }, this)\n        }, void 0, false, {\n            fileName: \"/home/jeonghs/workspace/nextitslm/frontend/src/pages/_app.tsx\",\n            lineNumber: 9,\n            columnNumber: 7\n        }, this)\n    }, void 0, false, {\n        fileName: \"/home/jeonghs/workspace/nextitslm/frontend/src/pages/_app.tsx\",\n        lineNumber: 8,\n        columnNumber: 5\n    }, this);\n}\n\n__webpack_async_result__();\n} catch(e) { __webpack_async_result__(e); } });//# sourceURL=[module]\n//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiLi9zcmMvcGFnZXMvX2FwcC50c3giLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7Ozs7O0FBQThCO0FBQ0M7QUFFcUI7QUFFckMsU0FBU0UsSUFBSSxFQUFFQyxTQUFTLEVBQUVDLFNBQVMsRUFBWTtJQUM1RCxxQkFDRSw4REFBQ0osMkNBQWM7a0JBQ2IsNEVBQUNDLDREQUFXQTtzQkFDViw0RUFBQ0U7Z0JBQVcsR0FBR0MsU0FBUzs7Ozs7Ozs7Ozs7Ozs7OztBQUloQyIsInNvdXJjZXMiOlsid2VicGFjazovL2NoYXRib3QtZnJvbnRlbmQvLi9zcmMvcGFnZXMvX2FwcC50c3g/ZjlkNiJdLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgJ0Avc3R5bGVzL2dsb2JhbHMuY3NzJztcbmltcG9ydCAqIGFzIFJlYWN0IGZyb20gJ3JlYWN0JztcbmltcG9ydCB0eXBlIHsgQXBwUHJvcHMgfSBmcm9tICduZXh0L2FwcCc7XG5pbXBvcnQgeyBBcHBQcm92aWRlciB9IGZyb20gJy4uL3V0aWxzL211aS1wcm92aWRlcic7XG5cbmV4cG9ydCBkZWZhdWx0IGZ1bmN0aW9uIEFwcCh7IENvbXBvbmVudCwgcGFnZVByb3BzIH06IEFwcFByb3BzKSB7XG4gIHJldHVybiAoXG4gICAgPFJlYWN0LkZyYWdtZW50PlxuICAgICAgPEFwcFByb3ZpZGVyPlxuICAgICAgICA8Q29tcG9uZW50IHsuLi5wYWdlUHJvcHN9IC8+XG4gICAgICA8L0FwcFByb3ZpZGVyPlxuICAgIDwvUmVhY3QuRnJhZ21lbnQ+XG4gICk7XG59XG4iXSwibmFtZXMiOlsiUmVhY3QiLCJBcHBQcm92aWRlciIsIkFwcCIsIkNvbXBvbmVudCIsInBhZ2VQcm9wcyIsIkZyYWdtZW50Il0sInNvdXJjZVJvb3QiOiIifQ==\n//# sourceURL=webpack-internal:///./src/pages/_app.tsx\n");

/***/ }),

/***/ "./src/styles/theme.ts":
/*!*****************************!*\
  !*** ./src/styles/theme.ts ***!
  \*****************************/
/***/ ((module, __webpack_exports__, __webpack_require__) => {

"use strict";
eval("__webpack_require__.a(module, async (__webpack_handle_async_dependencies__, __webpack_async_result__) => { try {\n__webpack_require__.r(__webpack_exports__);\n/* harmony export */ __webpack_require__.d(__webpack_exports__, {\n/* harmony export */   \"default\": () => (__WEBPACK_DEFAULT_EXPORT__)\n/* harmony export */ });\n/* harmony import */ var _mui_material_styles__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @mui/material/styles */ \"@mui/material/styles\");\nvar __webpack_async_dependencies__ = __webpack_handle_async_dependencies__([_mui_material_styles__WEBPACK_IMPORTED_MODULE_0__]);\n_mui_material_styles__WEBPACK_IMPORTED_MODULE_0__ = (__webpack_async_dependencies__.then ? (await __webpack_async_dependencies__)() : __webpack_async_dependencies__)[0];\n\n// Create a theme instance\nconst theme = (0,_mui_material_styles__WEBPACK_IMPORTED_MODULE_0__.createTheme)({\n    palette: {\n        primary: {\n            main: \"#1976d2\"\n        },\n        secondary: {\n            main: \"#dc004e\"\n        },\n        background: {\n            default: \"#f5f5f5\"\n        }\n    },\n    typography: {\n        fontFamily: [\n            \"-apple-system\",\n            \"BlinkMacSystemFont\",\n            '\"Segoe UI\"',\n            \"Roboto\",\n            '\"Helvetica Neue\"',\n            \"Arial\",\n            \"sans-serif\",\n            '\"Apple Color Emoji\"',\n            '\"Segoe UI Emoji\"',\n            '\"Segoe UI Symbol\"'\n        ].join(\",\")\n    }\n});\n/* harmony default export */ const __WEBPACK_DEFAULT_EXPORT__ = (theme);\n\n__webpack_async_result__();\n} catch(e) { __webpack_async_result__(e); } });//# sourceURL=[module]\n//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiLi9zcmMvc3R5bGVzL3RoZW1lLnRzIiwibWFwcGluZ3MiOiI7Ozs7Ozs7O0FBQW1EO0FBRW5ELDBCQUEwQjtBQUMxQixNQUFNQyxRQUFRRCxpRUFBV0EsQ0FBQztJQUN4QkUsU0FBUztRQUNQQyxTQUFTO1lBQ1BDLE1BQU07UUFDUjtRQUNBQyxXQUFXO1lBQ1RELE1BQU07UUFDUjtRQUNBRSxZQUFZO1lBQ1ZDLFNBQVM7UUFDWDtJQUNGO0lBQ0FDLFlBQVk7UUFDVkMsWUFBWTtZQUNWO1lBQ0E7WUFDQTtZQUNBO1lBQ0E7WUFDQTtZQUNBO1lBQ0E7WUFDQTtZQUNBO1NBQ0QsQ0FBQ0MsSUFBSSxDQUFDO0lBQ1Q7QUFDRjtBQUVBLGlFQUFlVCxLQUFLQSxFQUFDIiwic291cmNlcyI6WyJ3ZWJwYWNrOi8vY2hhdGJvdC1mcm9udGVuZC8uL3NyYy9zdHlsZXMvdGhlbWUudHM/NTE2MSJdLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgeyBjcmVhdGVUaGVtZSB9IGZyb20gJ0BtdWkvbWF0ZXJpYWwvc3R5bGVzJztcblxuLy8gQ3JlYXRlIGEgdGhlbWUgaW5zdGFuY2VcbmNvbnN0IHRoZW1lID0gY3JlYXRlVGhlbWUoe1xuICBwYWxldHRlOiB7XG4gICAgcHJpbWFyeToge1xuICAgICAgbWFpbjogJyMxOTc2ZDInLFxuICAgIH0sXG4gICAgc2Vjb25kYXJ5OiB7XG4gICAgICBtYWluOiAnI2RjMDA0ZScsXG4gICAgfSxcbiAgICBiYWNrZ3JvdW5kOiB7XG4gICAgICBkZWZhdWx0OiAnI2Y1ZjVmNScsXG4gICAgfSxcbiAgfSxcbiAgdHlwb2dyYXBoeToge1xuICAgIGZvbnRGYW1pbHk6IFtcbiAgICAgICctYXBwbGUtc3lzdGVtJyxcbiAgICAgICdCbGlua01hY1N5c3RlbUZvbnQnLFxuICAgICAgJ1wiU2Vnb2UgVUlcIicsXG4gICAgICAnUm9ib3RvJyxcbiAgICAgICdcIkhlbHZldGljYSBOZXVlXCInLFxuICAgICAgJ0FyaWFsJyxcbiAgICAgICdzYW5zLXNlcmlmJyxcbiAgICAgICdcIkFwcGxlIENvbG9yIEVtb2ppXCInLFxuICAgICAgJ1wiU2Vnb2UgVUkgRW1vamlcIicsXG4gICAgICAnXCJTZWdvZSBVSSBTeW1ib2xcIicsXG4gICAgXS5qb2luKCcsJyksXG4gIH0sXG59KTtcblxuZXhwb3J0IGRlZmF1bHQgdGhlbWU7XG4iXSwibmFtZXMiOlsiY3JlYXRlVGhlbWUiLCJ0aGVtZSIsInBhbGV0dGUiLCJwcmltYXJ5IiwibWFpbiIsInNlY29uZGFyeSIsImJhY2tncm91bmQiLCJkZWZhdWx0IiwidHlwb2dyYXBoeSIsImZvbnRGYW1pbHkiLCJqb2luIl0sInNvdXJjZVJvb3QiOiIifQ==\n//# sourceURL=webpack-internal:///./src/styles/theme.ts\n");

/***/ }),

/***/ "./src/utils/mui-provider.tsx":
/*!************************************!*\
  !*** ./src/utils/mui-provider.tsx ***!
  \************************************/
/***/ ((module, __webpack_exports__, __webpack_require__) => {

"use strict";
eval("__webpack_require__.a(module, async (__webpack_handle_async_dependencies__, __webpack_async_result__) => { try {\n__webpack_require__.r(__webpack_exports__);\n/* harmony export */ __webpack_require__.d(__webpack_exports__, {\n/* harmony export */   AppProvider: () => (/* binding */ AppProvider),\n/* harmony export */   MuiProvider: () => (/* binding */ MuiProvider)\n/* harmony export */ });\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react/jsx-dev-runtime */ \"react/jsx-dev-runtime\");\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__);\n/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! react */ \"react\");\n/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_1__);\n/* harmony import */ var _mui_material_styles__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @mui/material/styles */ \"@mui/material/styles\");\n/* harmony import */ var _mui_material_CssBaseline__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! @mui/material/CssBaseline */ \"@mui/material/CssBaseline\");\n/* harmony import */ var _styles_theme__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(/*! ../styles/theme */ \"./src/styles/theme.ts\");\n/* harmony import */ var _contexts_FileContext__WEBPACK_IMPORTED_MODULE_5__ = __webpack_require__(/*! ../contexts/FileContext */ \"./src/contexts/FileContext.tsx\");\nvar __webpack_async_dependencies__ = __webpack_handle_async_dependencies__([_mui_material_styles__WEBPACK_IMPORTED_MODULE_2__, _mui_material_CssBaseline__WEBPACK_IMPORTED_MODULE_3__, _styles_theme__WEBPACK_IMPORTED_MODULE_4__]);\n([_mui_material_styles__WEBPACK_IMPORTED_MODULE_2__, _mui_material_CssBaseline__WEBPACK_IMPORTED_MODULE_3__, _styles_theme__WEBPACK_IMPORTED_MODULE_4__] = __webpack_async_dependencies__.then ? (await __webpack_async_dependencies__)() : __webpack_async_dependencies__);\n\n\n\n\n\n\n/**\n * Combined provider that wraps components with both Material-UI and FileContext\n * This avoids issues with useContext null references by ensuring proper provider setup\n */ function AppProvider({ children }) {\n    // FileContext state\n    const [checkedFiles, setCheckedFiles] = (0,react__WEBPACK_IMPORTED_MODULE_1__.useState)([]);\n    // Remove server-side injected CSS\n    react__WEBPACK_IMPORTED_MODULE_1___default().useEffect(()=>{\n        const jssStyles = document.querySelector(\"#jss-server-side\");\n        if (jssStyles) {\n            jssStyles.parentElement?.removeChild(jssStyles);\n        }\n    }, []);\n    // FileContext value\n    const fileContextValue = {\n        checkedFiles,\n        setCheckedFiles\n    };\n    return /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(_mui_material_styles__WEBPACK_IMPORTED_MODULE_2__.ThemeProvider, {\n        theme: _styles_theme__WEBPACK_IMPORTED_MODULE_4__[\"default\"],\n        children: [\n            /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(_mui_material_CssBaseline__WEBPACK_IMPORTED_MODULE_3__[\"default\"], {}, void 0, false, {\n                fileName: \"/home/jeonghs/workspace/nextitslm/frontend/src/utils/mui-provider.tsx\",\n                lineNumber: 35,\n                columnNumber: 7\n            }, this),\n            /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(_contexts_FileContext__WEBPACK_IMPORTED_MODULE_5__.FileContext.Provider, {\n                value: fileContextValue,\n                children: children\n            }, void 0, false, {\n                fileName: \"/home/jeonghs/workspace/nextitslm/frontend/src/utils/mui-provider.tsx\",\n                lineNumber: 36,\n                columnNumber: 7\n            }, this)\n        ]\n    }, void 0, true, {\n        fileName: \"/home/jeonghs/workspace/nextitslm/frontend/src/utils/mui-provider.tsx\",\n        lineNumber: 34,\n        columnNumber: 5\n    }, this);\n}\n/**\n * Legacy MuiProvider for backward compatibility\n */ function MuiProvider({ children }) {\n    return /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(_mui_material_styles__WEBPACK_IMPORTED_MODULE_2__.ThemeProvider, {\n        theme: _styles_theme__WEBPACK_IMPORTED_MODULE_4__[\"default\"],\n        children: [\n            /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(_mui_material_CssBaseline__WEBPACK_IMPORTED_MODULE_3__[\"default\"], {}, void 0, false, {\n                fileName: \"/home/jeonghs/workspace/nextitslm/frontend/src/utils/mui-provider.tsx\",\n                lineNumber: 49,\n                columnNumber: 7\n            }, this),\n            children\n        ]\n    }, void 0, true, {\n        fileName: \"/home/jeonghs/workspace/nextitslm/frontend/src/utils/mui-provider.tsx\",\n        lineNumber: 48,\n        columnNumber: 5\n    }, this);\n}\n\n__webpack_async_result__();\n} catch(e) { __webpack_async_result__(e); } });//# sourceURL=[module]\n//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiLi9zcmMvdXRpbHMvbXVpLXByb3ZpZGVyLnRzeCIsIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7OztBQUF3QztBQUNhO0FBQ0Q7QUFDaEI7QUFDa0I7QUFNdEQ7OztDQUdDLEdBQ00sU0FBU00sWUFBWSxFQUFFQyxRQUFRLEVBQW9CO0lBQ3hELG9CQUFvQjtJQUNwQixNQUFNLENBQUNDLGNBQWNDLGdCQUFnQixHQUFHUiwrQ0FBUUEsQ0FBVyxFQUFFO0lBRTdELGtDQUFrQztJQUNsQ0Qsc0RBQWUsQ0FBQztRQUNkLE1BQU1XLFlBQVlDLFNBQVNDLGFBQWEsQ0FBQztRQUN6QyxJQUFJRixXQUFXO1lBQ2JBLFVBQVVHLGFBQWEsRUFBRUMsWUFBWUo7UUFDdkM7SUFDRixHQUFHLEVBQUU7SUFFTCxvQkFBb0I7SUFDcEIsTUFBTUssbUJBQW1CO1FBQ3ZCUjtRQUNBQztJQUNGO0lBRUEscUJBQ0UsOERBQUNQLCtEQUFhQTtRQUFDRSxPQUFPQSxxREFBS0E7OzBCQUN6Qiw4REFBQ0QsaUVBQVdBOzs7OzswQkFDWiw4REFBQ0UsOERBQVdBLENBQUNZLFFBQVE7Z0JBQUNDLE9BQU9GOzBCQUMxQlQ7Ozs7Ozs7Ozs7OztBQUlUO0FBRUE7O0NBRUMsR0FDTSxTQUFTWSxZQUFZLEVBQUVaLFFBQVEsRUFBb0I7SUFDeEQscUJBQ0UsOERBQUNMLCtEQUFhQTtRQUFDRSxPQUFPQSxxREFBS0E7OzBCQUN6Qiw4REFBQ0QsaUVBQVdBOzs7OztZQUNYSTs7Ozs7OztBQUdQIiwic291cmNlcyI6WyJ3ZWJwYWNrOi8vY2hhdGJvdC1mcm9udGVuZC8uL3NyYy91dGlscy9tdWktcHJvdmlkZXIudHN4P2IwNDgiXSwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0IFJlYWN0LCB7IHVzZVN0YXRlIH0gZnJvbSAncmVhY3QnO1xuaW1wb3J0IHsgVGhlbWVQcm92aWRlciB9IGZyb20gJ0BtdWkvbWF0ZXJpYWwvc3R5bGVzJztcbmltcG9ydCBDc3NCYXNlbGluZSBmcm9tICdAbXVpL21hdGVyaWFsL0Nzc0Jhc2VsaW5lJztcbmltcG9ydCB0aGVtZSBmcm9tICcuLi9zdHlsZXMvdGhlbWUnO1xuaW1wb3J0IHsgRmlsZUNvbnRleHQgfSBmcm9tICcuLi9jb250ZXh0cy9GaWxlQ29udGV4dCc7XG5cbmludGVyZmFjZSBBcHBQcm92aWRlclByb3BzIHtcbiAgY2hpbGRyZW46IFJlYWN0LlJlYWN0Tm9kZTtcbn1cblxuLyoqXG4gKiBDb21iaW5lZCBwcm92aWRlciB0aGF0IHdyYXBzIGNvbXBvbmVudHMgd2l0aCBib3RoIE1hdGVyaWFsLVVJIGFuZCBGaWxlQ29udGV4dFxuICogVGhpcyBhdm9pZHMgaXNzdWVzIHdpdGggdXNlQ29udGV4dCBudWxsIHJlZmVyZW5jZXMgYnkgZW5zdXJpbmcgcHJvcGVyIHByb3ZpZGVyIHNldHVwXG4gKi9cbmV4cG9ydCBmdW5jdGlvbiBBcHBQcm92aWRlcih7IGNoaWxkcmVuIH06IEFwcFByb3ZpZGVyUHJvcHMpIHtcbiAgLy8gRmlsZUNvbnRleHQgc3RhdGVcbiAgY29uc3QgW2NoZWNrZWRGaWxlcywgc2V0Q2hlY2tlZEZpbGVzXSA9IHVzZVN0YXRlPHN0cmluZ1tdPihbXSk7XG4gIFxuICAvLyBSZW1vdmUgc2VydmVyLXNpZGUgaW5qZWN0ZWQgQ1NTXG4gIFJlYWN0LnVzZUVmZmVjdCgoKSA9PiB7XG4gICAgY29uc3QganNzU3R5bGVzID0gZG9jdW1lbnQucXVlcnlTZWxlY3RvcignI2pzcy1zZXJ2ZXItc2lkZScpO1xuICAgIGlmIChqc3NTdHlsZXMpIHtcbiAgICAgIGpzc1N0eWxlcy5wYXJlbnRFbGVtZW50Py5yZW1vdmVDaGlsZChqc3NTdHlsZXMpO1xuICAgIH1cbiAgfSwgW10pO1xuXG4gIC8vIEZpbGVDb250ZXh0IHZhbHVlXG4gIGNvbnN0IGZpbGVDb250ZXh0VmFsdWUgPSB7XG4gICAgY2hlY2tlZEZpbGVzLFxuICAgIHNldENoZWNrZWRGaWxlc1xuICB9O1xuXG4gIHJldHVybiAoXG4gICAgPFRoZW1lUHJvdmlkZXIgdGhlbWU9e3RoZW1lfT5cbiAgICAgIDxDc3NCYXNlbGluZSAvPlxuICAgICAgPEZpbGVDb250ZXh0LlByb3ZpZGVyIHZhbHVlPXtmaWxlQ29udGV4dFZhbHVlfT5cbiAgICAgICAge2NoaWxkcmVufVxuICAgICAgPC9GaWxlQ29udGV4dC5Qcm92aWRlcj5cbiAgICA8L1RoZW1lUHJvdmlkZXI+XG4gICk7XG59XG5cbi8qKlxuICogTGVnYWN5IE11aVByb3ZpZGVyIGZvciBiYWNrd2FyZCBjb21wYXRpYmlsaXR5XG4gKi9cbmV4cG9ydCBmdW5jdGlvbiBNdWlQcm92aWRlcih7IGNoaWxkcmVuIH06IEFwcFByb3ZpZGVyUHJvcHMpIHtcbiAgcmV0dXJuIChcbiAgICA8VGhlbWVQcm92aWRlciB0aGVtZT17dGhlbWV9PlxuICAgICAgPENzc0Jhc2VsaW5lIC8+XG4gICAgICB7Y2hpbGRyZW59XG4gICAgPC9UaGVtZVByb3ZpZGVyPlxuICApO1xufVxuIl0sIm5hbWVzIjpbIlJlYWN0IiwidXNlU3RhdGUiLCJUaGVtZVByb3ZpZGVyIiwiQ3NzQmFzZWxpbmUiLCJ0aGVtZSIsIkZpbGVDb250ZXh0IiwiQXBwUHJvdmlkZXIiLCJjaGlsZHJlbiIsImNoZWNrZWRGaWxlcyIsInNldENoZWNrZWRGaWxlcyIsInVzZUVmZmVjdCIsImpzc1N0eWxlcyIsImRvY3VtZW50IiwicXVlcnlTZWxlY3RvciIsInBhcmVudEVsZW1lbnQiLCJyZW1vdmVDaGlsZCIsImZpbGVDb250ZXh0VmFsdWUiLCJQcm92aWRlciIsInZhbHVlIiwiTXVpUHJvdmlkZXIiXSwic291cmNlUm9vdCI6IiJ9\n//# sourceURL=webpack-internal:///./src/utils/mui-provider.tsx\n");

/***/ }),

/***/ "./src/styles/globals.css":
/*!********************************!*\
  !*** ./src/styles/globals.css ***!
  \********************************/
/***/ (() => {



/***/ }),

/***/ "react":
/*!************************!*\
  !*** external "react" ***!
  \************************/
/***/ ((module) => {

"use strict";
module.exports = require("react");

/***/ }),

/***/ "react/jsx-dev-runtime":
/*!****************************************!*\
  !*** external "react/jsx-dev-runtime" ***!
  \****************************************/
/***/ ((module) => {

"use strict";
module.exports = require("react/jsx-dev-runtime");

/***/ }),

/***/ "@mui/material/CssBaseline":
/*!********************************************!*\
  !*** external "@mui/material/CssBaseline" ***!
  \********************************************/
/***/ ((module) => {

"use strict";
module.exports = import("@mui/material/CssBaseline");;

/***/ }),

/***/ "@mui/material/styles":
/*!***************************************!*\
  !*** external "@mui/material/styles" ***!
  \***************************************/
/***/ ((module) => {

"use strict";
module.exports = import("@mui/material/styles");;

/***/ })

};
;

// load runtime
var __webpack_require__ = require("../webpack-runtime.js");
__webpack_require__.C(exports);
var __webpack_exec__ = (moduleId) => (__webpack_require__(__webpack_require__.s = moduleId))
var __webpack_exports__ = (__webpack_exec__("./src/pages/_app.tsx"));
module.exports = __webpack_exports__;

})();