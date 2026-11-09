// Resource definition for a fresh Penny environment. Do not apply over the live
// manually-created VM without reviewing an Azure what-if and the existing IDs.
// Application releases use scripts/deploy_vm.sh; they do not reprovision the VM.
targetScope = 'resourceGroup'

@description('Use a region allowed by your subscription policy and with the selected VM SKU available.')
param location string = resourceGroup().location

@minLength(3)
@maxLength(40)
@description('Unique deployment prefix for the VM, network and disks.')
param namePrefix string

@description('Current deployment uses two vCPUs and 4 GiB RAM; verify regional availability before provisioning.')
param vmSize string = 'Standard_B2als_v2'

param adminUsername string = 'azureuser'

@secure()
@description('SSH PUBLIC key only. Never supply the private PEM file or a password.')
param sshPublicKey string

@description('Administrator source address/CIDR, normally your public IPv4 address followed by /32.')
param sshSourceCidr string

@minLength(3)
@maxLength(63)
param dnsLabel string

@description('Pin a supported image version for a reproducible build; latest receives current Ubuntu patches.')
param imageVersion string = 'latest'

@description('Optional existing data-disk resource ID for an explicitly reviewed restore. Empty creates a fresh empty64 GiB disk. No filesystem is formatted by this template.')
param existingDataDiskId string = ''

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-${namePrefix}'
  location: location
  properties: {
    securityRules: [
      {
        name: 'allow-ssh-admin'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: sshSourceCidr
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
      {
        name: 'allow-http'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '80'
        }
      }
      {
        name: 'allow-https'
        properties: {
          priority: 120
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${namePrefix}'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.20.0.0/16'] }
  }
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'snet-app'
  properties: {
    addressPrefix: '10.20.1.0/24'
    defaultOutboundAccess: false
    networkSecurityGroup: { id: nsg.id }
  }
}

// Explicit VM-associated Standard public IP provides the outbound path.
// App, MCP, model gateway, Redis and renderer ports stay private in Compose.
resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-${namePrefix}'
  location: location
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
    dnsSettings: { domainNameLabel: dnsLabel }
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: 'nic-${namePrefix}'
  location: location
  properties: {
    enableIPForwarding: false
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          primary: true
          privateIPAllocationMethod: 'Dynamic'
          privateIPAddressVersion: 'IPv4'
          subnet: { id: subnet.id }
          publicIPAddress: { id: publicIp.id }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-11-01' = {
  name: 'vm-${namePrefix}-01'
  location: location
  properties: {
    hardwareProfile: { vmSize: vmSize }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: { secureBootEnabled: true, vTpmEnabled: true }
    }
    osProfile: {
      computerName: 'vm-${namePrefix}-01'
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: {
          publicKeys: [
            { path: '/home/${adminUsername}/.ssh/authorized_keys', keyData: sshPublicKey }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: imageVersion
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: 30
        caching: 'ReadWrite'
        deleteOption: 'Detach'
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
      }
      dataDisks: [
        {
          name: empty(existingDataDiskId) ? 'disk-${namePrefix}-data' : last(split(existingDataDiskId, '/'))
          lun: 0
          createOption: empty(existingDataDiskId) ? 'Empty' : 'Attach'
          diskSizeGB: 64
          caching: 'None'
          deleteOption: 'Detach'
          managedDisk: empty(existingDataDiskId) ? { storageAccountType: 'StandardSSD_LRS' } : { id: existingDataDiskId }
        }
      ]
    }
    networkProfile: {
      networkInterfaces: [
        { id: nic.id, properties: { primary: true, deleteOption: 'Detach' } }
      ]
    }
  }
}

output vmName string = vm.name
output publicHostname string = publicIp.properties.dnsSettings.fqdn
output applicationUrl string = 'https://${publicIp.properties.dnsSettings.fqdn}'
