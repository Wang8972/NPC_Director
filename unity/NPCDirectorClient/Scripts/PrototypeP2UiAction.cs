using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeP2UiAction : MonoBehaviour
    {
        [SerializeField] private PrototypeP2GameController controller;
        [SerializeField] private string command;

        public string Command => command;

        public void Configure(PrototypeP2GameController gameController, string configuredCommand)
        {
            controller = gameController;
            command = configuredCommand;
        }

        public void InvokeAction()
        {
            controller?.ExecuteCommand(command);
        }
    }
}
