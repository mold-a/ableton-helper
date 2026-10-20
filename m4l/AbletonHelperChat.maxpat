{
  "patcher": {
    "fileversion": 1,
    "appversion": {
      "major": 8,
      "minor": 6,
      "revision": 2,
      "architecture": "x64",
      "modernui": 1
    },
    "classnamespace": "box",
    "rect": [
      100.0,
      100.0,
      520.0,
      360.0
    ],
    "openinpresentation": 1,
    "devicewidth": 264.0,
    "bglocked": 0,
    "default_fontsize": 12.0,
    "default_fontface": 0,
    "gridonopen": 1,
    "gridsize": [
      15.0,
      15.0
    ],
    "gridsnaponopen": 1,
    "toolbarvisible": 1,
    "boxanimatetime": 200,
    "imprint": 0,
    "enablehscroll": 1,
    "enablevscroll": 1,
    "boxes": [
      {
        "box": {
          "id": "obj-1",
          "maxclass": "comment",
          "numinlets": 1,
          "numoutlets": 0,
          "patching_rect": [
            20.0,
            10.0,
            200.0,
            22.0
          ],
          "text": "Ableton Helper",
          "fontsize": 14.0,
          "presentation": 1,
          "presentation_rect": [
            8.0,
            6.0,
            200.0,
            22.0
          ],
          "fontname": "Arial Bold"
        }
      },
      {
        "box": {
          "id": "obj-2",
          "maxclass": "live.text",
          "numinlets": 1,
          "numoutlets": 2,
          "outlettype": [
            "",
            "float"
          ],
          "parameter_enable": 0,
          "mode": 0,
          "text": "Открыть чат",
          "texton": "Открыть чат",
          "varname": "open_chat",
          "patching_rect": [
            20.0,
            50.0,
            100.0,
            24.0
          ],
          "presentation": 1,
          "presentation_rect": [
            8.0,
            34.0,
            130.0,
            28.0
          ],
          "fontsize": 12.0
        }
      },
      {
        "box": {
          "id": "obj-3",
          "maxclass": "newobj",
          "numinlets": 2,
          "numoutlets": 2,
          "outlettype": [
            "bang",
            ""
          ],
          "patching_rect": [
            20.0,
            85.0,
            40.0,
            22.0
          ],
          "text": "sel 1"
        }
      },
      {
        "box": {
          "id": "obj-4",
          "maxclass": "message",
          "numinlets": 2,
          "numoutlets": 1,
          "outlettype": [
            ""
          ],
          "patching_rect": [
            20.0,
            115.0,
            40.0,
            22.0
          ],
          "text": "open"
        }
      },
      {
        "box": {
          "id": "obj-5",
          "maxclass": "newobj",
          "numinlets": 1,
          "numoutlets": 1,
          "outlettype": [
            ""
          ],
          "patching_rect": [
            20.0,
            145.0,
            60.0,
            22.0
          ],
          "text": "pcontrol"
        }
      },
      {
        "box": {
          "id": "obj-6",
          "maxclass": "newobj",
          "numinlets": 2,
          "numoutlets": 1,
          "outlettype": [
            ""
          ],
          "patching_rect": [
            20.0,
            185.0,
            70.0,
            22.0
          ],
          "text": "p chat",
          "patcher": {
            "fileversion": 1,
            "appversion": {
              "major": 8,
              "minor": 6,
              "revision": 2,
              "architecture": "x64",
              "modernui": 1
            },
            "classnamespace": "box",
            "rect": [
              80.0,
              100.0,
              420.0,
              700.0
            ],
            "openinpresentation": 1,
            "bglocked": 0,
            "default_fontsize": 12.0,
            "boxes": [
              {
                "box": {
                  "id": "obj-1",
                  "maxclass": "inlet",
                  "numinlets": 0,
                  "numoutlets": 1,
                  "outlettype": [
                    ""
                  ],
                  "patching_rect": [
                    20.0,
                    20.0,
                    30.0,
                    30.0
                  ],
                  "comment": "open (pcontrol)"
                }
              },
              {
                "box": {
                  "id": "obj-2",
                  "maxclass": "inlet",
                  "numinlets": 0,
                  "numoutlets": 1,
                  "outlettype": [
                    ""
                  ],
                  "patching_rect": [
                    160.0,
                    20.0,
                    30.0,
                    30.0
                  ],
                  "comment": "messages to jweb"
                }
              },
              {
                "box": {
                  "id": "obj-3",
                  "maxclass": "jweb",
                  "numinlets": 1,
                  "numoutlets": 3,
                  "outlettype": [
                    "",
                    "",
                    ""
                  ],
                  "url": "http://127.0.0.1:8765/",
                  "patching_rect": [
                    160.0,
                    70.0,
                    420.0,
                    700.0
                  ],
                  "presentation": 1,
                  "presentation_rect": [
                    0.0,
                    0.0,
                    420.0,
                    700.0
                  ]
                }
              },
              {
                "box": {
                  "id": "obj-4",
                  "maxclass": "outlet",
                  "numinlets": 1,
                  "numoutlets": 0,
                  "patching_rect": [
                    160.0,
                    790.0,
                    30.0,
                    30.0
                  ],
                  "comment": "loaded (bang)"
                }
              },
              {
                "box": {
                  "id": "obj-5",
                  "maxclass": "newobj",
                  "numinlets": 1,
                  "numoutlets": 1,
                  "outlettype": [
                    "bang"
                  ],
                  "patching_rect": [
                    20.0,
                    100.0,
                    60.0,
                    22.0
                  ],
                  "text": "loadbang"
                }
              },
              {
                "box": {
                  "id": "obj-6",
                  "maxclass": "message",
                  "numinlets": 2,
                  "numoutlets": 1,
                  "outlettype": [
                    ""
                  ],
                  "patching_rect": [
                    20.0,
                    130.0,
                    150.0,
                    22.0
                  ],
                  "text": "window flags float, window exec"
                }
              },
              {
                "box": {
                  "id": "obj-7",
                  "maxclass": "newobj",
                  "numinlets": 1,
                  "numoutlets": 2,
                  "outlettype": [
                    "",
                    ""
                  ],
                  "patching_rect": [
                    20.0,
                    160.0,
                    70.0,
                    22.0
                  ],
                  "text": "thispatcher"
                }
              }
            ],
            "lines": [
              {
                "patchline": {
                  "source": [
                    "obj-2",
                    0
                  ],
                  "destination": [
                    "obj-3",
                    0
                  ]
                }
              },
              {
                "patchline": {
                  "source": [
                    "obj-3",
                    2
                  ],
                  "destination": [
                    "obj-4",
                    0
                  ]
                }
              },
              {
                "patchline": {
                  "source": [
                    "obj-5",
                    0
                  ],
                  "destination": [
                    "obj-6",
                    0
                  ]
                }
              },
              {
                "patchline": {
                  "source": [
                    "obj-6",
                    0
                  ],
                  "destination": [
                    "obj-7",
                    0
                  ]
                }
              }
            ]
          }
        }
      },
      {
        "box": {
          "id": "obj-7",
          "maxclass": "live.text",
          "numinlets": 1,
          "numoutlets": 2,
          "outlettype": [
            "",
            "float"
          ],
          "parameter_enable": 0,
          "mode": 0,
          "text": "Обновить",
          "texton": "Обновить",
          "varname": "refresh_chat",
          "patching_rect": [
            160.0,
            50.0,
            90.0,
            24.0
          ],
          "presentation": 1,
          "presentation_rect": [
            146.0,
            34.0,
            110.0,
            28.0
          ],
          "fontsize": 12.0
        }
      },
      {
        "box": {
          "id": "obj-8",
          "maxclass": "newobj",
          "numinlets": 2,
          "numoutlets": 2,
          "outlettype": [
            "bang",
            ""
          ],
          "patching_rect": [
            160.0,
            85.0,
            40.0,
            22.0
          ],
          "text": "sel 1"
        }
      },
      {
        "box": {
          "id": "obj-9",
          "maxclass": "message",
          "numinlets": 2,
          "numoutlets": 1,
          "outlettype": [
            ""
          ],
          "patching_rect": [
            160.0,
            115.0,
            170.0,
            22.0
          ],
          "text": "url http://127.0.0.1:8765/"
        }
      },
      {
        "box": {
          "id": "obj-10",
          "maxclass": "comment",
          "numinlets": 1,
          "numoutlets": 0,
          "patching_rect": [
            160.0,
            230.0,
            200.0,
            20.0
          ],
          "text": "Сервер: 127.0.0.1:8765",
          "fontsize": 11.0,
          "presentation": 1,
          "presentation_rect": [
            8.0,
            72.0,
            248.0,
            20.0
          ]
        }
      },
      {
        "box": {
          "id": "obj-11",
          "maxclass": "message",
          "numinlets": 2,
          "numoutlets": 1,
          "outlettype": [
            ""
          ],
          "patching_rect": [
            160.0,
            190.0,
            120.0,
            22.0
          ],
          "text": "set Чат загружен"
        }
      },
      {
        "box": {
          "id": "obj-12",
          "maxclass": "comment",
          "numinlets": 1,
          "numoutlets": 0,
          "patching_rect": [
            20.0,
            260.0,
            300.0,
            20.0
          ],
          "text": "Если чат пустой: запустите abhelper serve и нажмите «Обновить».",
          "fontsize": 10.0,
          "presentation": 1,
          "presentation_rect": [
            8.0,
            96.0,
            250.0,
            60.0
          ]
        }
      }
    ],
    "lines": [
      {
        "patchline": {
          "source": [
            "obj-2",
            0
          ],
          "destination": [
            "obj-3",
            0
          ]
        }
      },
      {
        "patchline": {
          "source": [
            "obj-3",
            0
          ],
          "destination": [
            "obj-4",
            0
          ]
        }
      },
      {
        "patchline": {
          "source": [
            "obj-4",
            0
          ],
          "destination": [
            "obj-5",
            0
          ]
        }
      },
      {
        "patchline": {
          "source": [
            "obj-5",
            0
          ],
          "destination": [
            "obj-6",
            0
          ]
        }
      },
      {
        "patchline": {
          "source": [
            "obj-7",
            0
          ],
          "destination": [
            "obj-8",
            0
          ]
        }
      },
      {
        "patchline": {
          "source": [
            "obj-8",
            0
          ],
          "destination": [
            "obj-9",
            0
          ]
        }
      },
      {
        "patchline": {
          "source": [
            "obj-9",
            0
          ],
          "destination": [
            "obj-6",
            1
          ]
        }
      },
      {
        "patchline": {
          "source": [
            "obj-6",
            0
          ],
          "destination": [
            "obj-11",
            0
          ]
        }
      },
      {
        "patchline": {
          "source": [
            "obj-11",
            0
          ],
          "destination": [
            "obj-10",
            0
          ]
        }
      }
    ],
    "dependency_cache": [],
    "autosave": 0
  }
}
