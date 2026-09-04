using UnityEngine;
using UnityEngine.UI;

namespace NPCDirector
{
    public sealed class PrototypeP3TextInput : MonoBehaviour
    {
        [SerializeField] private PrototypeP2Client client;
        [SerializeField] private PrototypeP2GameController controller;
        [SerializeField] private InputField inputField;

        public void Configure(
            PrototypeP2Client configuredClient,
            PrototypeP2GameController configuredController,
            InputField configuredInputField)
        {
            client = configuredClient;
            controller = configuredController;
            inputField = configuredInputField;
        }

        private void Update()
        {
            if (inputField != null && inputField.isFocused &&
                (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter)))
            {
                Submit();
            }
        }

        public void Submit()
        {
            if (client == null || controller == null || inputField == null)
            {
                return;
            }
            string value = inputField.text?.Trim();
            if (string.IsNullOrWhiteSpace(value) || controller.IsBusy)
            {
                return;
            }
            client.SendPlayerText(controller.SelectedNpcId, value);
            inputField.text = "";
            inputField.ActivateInputField();
        }
    }
}
